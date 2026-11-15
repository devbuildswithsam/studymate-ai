"""Tests for the FallbackManager, using FakeProviders only (no real APIs). SMA-22."""

import logging

import httpx2
import pytest

from app.services.llm.exceptions import (
    AllModelsFailedError,
    LLMConfigError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.services.llm.fake import FakeProvider
from app.services.llm.fallback import DEFAULT_COOLDOWN_SECONDS, FallbackManager
from app.services.llm.gemini import GeminiProvider
from app.services.llm.registry import ModelRegistry

MESSAGES = [{"role": "user", "content": "Explain osmosis."}]

# primary (tools) -> no-tools (no tool support) -> backup (tools)
REGISTRY = ModelRegistry.model_validate(
    {
        "version": 1,
        "providers": {"p": {"base_url": "https://p.test/v1", "api_key_env": "P_KEY"}},
        "models": [
            {
                "id": "primary",
                "provider": "p",
                "display_name": "Primary",
                "priority": 1,
                "supports_tools": True,
                "supports_json": True,
            },
            {
                "id": "no-tools",
                "provider": "p",
                "display_name": "No tools",
                "priority": 2,
                "supports_tools": False,
                "supports_json": True,
            },
            {
                "id": "backup",
                "provider": "p",
                "display_name": "Backup",
                "priority": 3,
                "supports_tools": True,
                "supports_json": True,
            },
            {
                "id": "off",
                "provider": "p",
                "display_name": "Off",
                "priority": 4,
                "supports_tools": True,
                "enabled": False,
            },
        ],
    }
)


class FakeClock:
    """A clock we move by hand, so cool-downs need no real waiting."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_manager(**fakes: FakeProvider):
    """A manager whose models are FakeProviders. Models not given answer normally."""
    providers = {m.id: FakeProvider(replies=[f"answer from {m.id}"]) for m in REGISTRY.models}
    providers.update({k.replace("_", "-"): v for k, v in fakes.items()})
    clock = FakeClock()
    manager = FallbackManager(REGISTRY, lambda m: providers[m.id], clock=clock)
    return manager, providers, clock


def rate_limited(retry_after=None):
    return FakeProvider(error=RateLimitedError("429", "p", retry_after=retry_after))


# --- Done when (1): a 429 leads to a labelled fallback answer ----------------------


def test_primary_429_falls_back_and_labels_the_answer():
    manager, providers, _ = make_manager(primary=rate_limited())

    result = manager.chat(MESSAGES)

    assert result.response.text == "answer from no-tools"  # next model by priority
    assert result.fallback_used is True
    assert result.requested_model == "primary"
    assert result.fallback_reason == "primary: rate-limited"
    assert len(providers["primary"].calls) == 1  # it was tried first


def test_no_fallback_when_the_primary_answers():
    manager, providers, _ = make_manager()

    result = manager.chat(MESSAGES)

    assert result.response.text == "answer from primary"
    assert result.fallback_used is False
    assert result.fallback_reason is None
    assert providers["no-tools"].calls == []  # never needed


# --- Done when (2): a tools request never falls back to a model without tools ------


def test_tools_request_skips_models_without_tool_support():
    manager, providers, _ = make_manager(primary=rate_limited())

    result = manager.chat(MESSAGES, needs=["tools"])

    assert result.response.text == "answer from backup"  # jumps over "no-tools"
    assert providers["no-tools"].calls == []


def test_tools_request_fails_rather_than_use_a_model_without_tools():
    manager, providers, _ = make_manager(
        primary=rate_limited(), backup=FakeProvider(error=ProviderUnavailableError("503", "p"))
    )

    with pytest.raises(AllModelsFailedError) as caught:
        manager.chat(MESSAGES, needs=["tools"])

    assert providers["no-tools"].calls == []  # still never used, even as a last resort
    assert caught.value.reasons == ["primary: rate-limited", "backup: unavailable"]


def test_choosing_a_model_without_a_needed_capability_is_an_error():
    manager, _, _ = make_manager()

    with pytest.raises(LLMConfigError, match="does not support tools"):
        manager.chat(MESSAGES, model_id="no-tools", needs=["tools"])


# --- Choosing a model --------------------------------------------------------------


def test_the_chosen_model_is_tried_first():
    manager, _, _ = make_manager()

    result = manager.chat(MESSAGES, model_id="backup")

    assert result.response.text == "answer from backup"
    assert result.requested_model == "backup"
    assert result.fallback_used is False


def test_chosen_model_falls_back_by_priority():
    manager, _, _ = make_manager(backup=rate_limited())

    result = manager.chat(MESSAGES, model_id="backup")

    assert result.response.text == "answer from primary"
    assert result.fallback_used is True


def test_disabled_models_are_never_used():
    manager, providers, _ = make_manager(
        primary=rate_limited(), no_tools=rate_limited(), backup=rate_limited()
    )

    with pytest.raises(AllModelsFailedError):
        manager.chat(MESSAGES)
    with pytest.raises(LLMConfigError, match="disabled"):
        manager.chat(MESSAGES, model_id="off")

    assert providers["off"].calls == []


# --- Rate-limit memory -------------------------------------------------------------


def test_rate_limited_model_is_skipped_until_its_cooldown_ends():
    manager, providers, clock = make_manager(primary=rate_limited(retry_after=30))

    manager.chat(MESSAGES)  # primary 429s -> cool down for 30 s
    assert manager.is_rate_limited("primary")

    second = manager.chat(MESSAGES)  # skipped without a request
    assert len(providers["primary"].calls) == 1
    assert second.fallback_reason == "primary: rate-limited (cooling down)"

    clock.advance(31)
    assert not manager.is_rate_limited("primary")
    manager.chat(MESSAGES)
    assert len(providers["primary"].calls) == 2  # tried again after the cool-down


def test_429_without_retry_after_uses_the_default_cooldown():
    manager, _, clock = make_manager(primary=rate_limited(retry_after=None))

    manager.chat(MESSAGES)

    clock.advance(DEFAULT_COOLDOWN_SECONDS - 1)
    assert manager.is_rate_limited("primary")
    clock.advance(2)
    assert not manager.is_rate_limited("primary")


# --- Other failures ----------------------------------------------------------------


@pytest.mark.parametrize(
    "error, reason",
    [
        (ProviderUnavailableError("503", "p", 503), "primary: unavailable"),
        (ProviderTimeoutError("slow", "p"), "primary: timed out"),
        (LLMConfigError("404", "p", 404), "primary: configuration error"),
    ],
)
def test_other_failures_also_fall_back_with_a_reason(error, reason):
    manager, _, _ = make_manager(primary=FakeProvider(error=error))

    result = manager.chat(MESSAGES)

    assert result.fallback_used is True
    assert result.fallback_reason == reason
    assert not manager.is_rate_limited("primary")  # only 429s start a cool-down


def test_gemini_bad_key_400_falls_back_as_a_loud_config_error(caplog):
    # SMA-54: the real Gemini adapter (fake HTTP server) as the primary model.
    body = [{"error": {"code": 400, "message": "Please pass a valid API key"}}]
    gemini = GeminiProvider(
        {"id": "primary", "supports_tools": True, "supports_json": True},
        api_key="test-key",
        base_url="https://gemini.example.test/v1",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(lambda r: httpx2.Response(400, json=body))
        ),
    )
    manager, _, _ = make_manager(primary=gemini)

    with caplog.at_level(logging.WARNING):
        result = manager.chat(MESSAGES)

    assert result.response.text == "answer from no-tools"  # next by priority
    assert result.fallback_reason == "primary: configuration error"
    assert [r.levelname for r in caplog.records] == ["ERROR"]  # loud, not a warning
    assert "test-key" not in caplog.text


def test_all_models_failing_raises_one_clear_error():
    manager, _, _ = make_manager(
        primary=rate_limited(),
        no_tools=FakeProvider(error=ProviderTimeoutError("slow", "p")),
        backup=FakeProvider(error=ProviderUnavailableError("503", "p")),
    )

    with pytest.raises(AllModelsFailedError, match="no model could answer") as caught:
        manager.chat(MESSAGES)

    assert caught.value.reasons == [
        "primary: rate-limited",
        "no-tools: timed out",
        "backup: unavailable",
    ]


def test_providers_are_built_once_and_reused():
    built = []

    def factory(model):
        built.append(model.id)
        return FakeProvider()

    manager = FallbackManager(REGISTRY, factory)
    manager.chat(MESSAGES)
    manager.chat(MESSAGES)

    assert built == ["primary"]


# --- Fallback can be switched off (SMA-26: "Use fallback if the model fails") -------


def test_without_fallback_only_the_chosen_model_is_tried():
    manager, providers, _ = make_manager(primary=rate_limited())

    with pytest.raises(AllModelsFailedError) as caught:
        manager.chat(MESSAGES, allow_fallback=False)

    assert caught.value.reasons == ["primary: rate-limited"]
    assert providers["no-tools"].calls == [] and providers["backup"].calls == []


def test_without_fallback_a_working_model_still_answers():
    manager, _, _ = make_manager()

    result = manager.chat(MESSAGES, model_id="backup", allow_fallback=False)

    assert result.response.text == "answer from backup"
    assert result.fallback_used is False
