"""Tests for the LLM providers: Gemini/Groq adapters (HTTP mocked) and the fake. SMA-21.

No real API is called: httpx2.MockTransport plays the provider's server.
"""

import json

import httpx2
import pytest

from app.services.llm.base import ChatOptions, LLMProvider
from app.services.llm.exceptions import (
    LLMConfigError,
    LLMError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.services.llm.fake import FakeProvider
from app.services.llm.gemini import GeminiProvider
from app.services.llm.groq import GroqProvider

MESSAGES = [{"role": "user", "content": "What is photosynthesis?"}]
MODEL_CONFIG = {"id": "test-model", "supports_tools": True, "supports_json": None}


def completion(content: str | None = "Plants make food from light.", finish_reason="stop"):
    """A minimal OpenAI-format chat completion, as a provider would send it."""
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
    }


def make_provider(provider_cls, respond):
    """Build an adapter whose 'server' is the respond(request) function. Returns (provider, sent)."""
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return respond(request)

    provider = provider_cls(
        MODEL_CONFIG,
        api_key="test-key",
        base_url="https://llm.example.test/v1",
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return provider, sent


ADAPTERS = [GeminiProvider, GroqProvider]


# --- Happy path -------------------------------------------------------------------


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_chat_returns_normalised_response(provider_cls):
    provider, _ = make_provider(provider_cls, lambda r: httpx2.Response(200, json=completion()))

    response = provider.chat(MESSAGES)

    assert response.text == "Plants make food from light."
    assert (response.tokens_in, response.tokens_out) == (12, 7)
    assert response.model == "test-model"
    assert response.provider == provider_cls.name
    assert response.latency_ms >= 0


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_chat_sends_model_messages_options_and_key(provider_cls):
    provider, sent = make_provider(provider_cls, lambda r: httpx2.Response(200, json=completion()))

    provider.chat(MESSAGES, ChatOptions(temperature=0.5, max_tokens=200, json_mode=True))

    request = sent[0]
    body = json.loads(request.content)
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    assert body["model"] == "test-model"
    assert body["messages"] == MESSAGES
    assert body["temperature"] == 0.5
    assert body["max_tokens"] == 200
    assert body["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_json_mode_off_sends_no_response_format(provider_cls):
    provider, sent = make_provider(provider_cls, lambda r: httpx2.Response(200, json=completion()))

    provider.chat(MESSAGES)

    assert "response_format" not in json.loads(sent[0].content)


# --- Errors become our types ------------------------------------------------------


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_429_with_retry_after_header_is_rate_limited(provider_cls):
    provider, _ = make_provider(
        provider_cls,
        lambda r: httpx2.Response(
            429, headers={"retry-after": "7"}, json={"error": {"message": "Rate limit reached"}}
        ),
    )

    with pytest.raises(RateLimitedError) as caught:
        provider.chat(MESSAGES)

    assert caught.value.retry_after == 7.0
    assert caught.value.provider == provider_cls.name
    assert "Rate limit reached" in str(caught.value)  # the provider's own message is kept


def test_gemini_429_reads_retry_delay_from_the_body():
    # Gemini quirk: the wait is in the body (google.rpc.RetryInfo), wrapped in a list.
    body = [
        {
            "error": {
                "code": 429,
                "message": "Quota exceeded",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "17s"}
                ],
            }
        }
    ]
    provider, _ = make_provider(GeminiProvider, lambda r: httpx2.Response(429, json=body))

    with pytest.raises(RateLimitedError) as caught:
        provider.chat(MESSAGES)

    assert caught.value.retry_after == 17.0
    assert "Quota exceeded" in str(caught.value)


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_429_without_a_wait_time_has_no_retry_after(provider_cls):
    provider, _ = make_provider(provider_cls, lambda r: httpx2.Response(429, json={}))

    with pytest.raises(RateLimitedError) as caught:
        provider.chat(MESSAGES)

    assert caught.value.retry_after is None


@pytest.mark.parametrize("provider_cls", ADAPTERS)
@pytest.mark.parametrize("status", [401, 403, 404])
def test_bad_key_or_model_is_a_config_error(provider_cls, status):
    provider, _ = make_provider(
        provider_cls, lambda r: httpx2.Response(status, json={"error": {"message": "nope"}})
    )

    with pytest.raises(LLMConfigError) as caught:
        provider.chat(MESSAGES)

    assert caught.value.status_code == status


@pytest.mark.parametrize("provider_cls", ADAPTERS)
@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_is_provider_unavailable(provider_cls, status):
    provider, _ = make_provider(provider_cls, lambda r: httpx2.Response(status, text="overloaded"))

    with pytest.raises(ProviderUnavailableError) as caught:
        provider.chat(MESSAGES)

    assert caught.value.status_code == status


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_timeout_is_provider_timeout(provider_cls):
    def too_slow(request):
        raise httpx2.ReadTimeout("no answer", request=request)

    provider, _ = make_provider(provider_cls, too_slow)

    with pytest.raises(ProviderTimeoutError):
        provider.chat(MESSAGES)


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_connection_failure_is_provider_unavailable(provider_cls):
    def unreachable(request):
        raise httpx2.ConnectError("no route", request=request)

    provider, _ = make_provider(provider_cls, unreachable)

    with pytest.raises(ProviderUnavailableError):
        provider.chat(MESSAGES)


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_failures_are_not_retried_by_the_sdk(provider_cls):
    provider, sent = make_provider(provider_cls, lambda r: httpx2.Response(503, text="busy"))

    with pytest.raises(ProviderUnavailableError):
        provider.chat(MESSAGES)

    assert len(sent) == 1  # max_retries=0: retry/fallback is decided in SMA-22


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_empty_answer_is_an_error(provider_cls):
    provider, _ = make_provider(
        provider_cls,
        lambda r: httpx2.Response(
            200, json=completion(content=None, finish_reason="content_filter")
        ),
    )

    with pytest.raises(LLMError, match="content_filter"):
        provider.chat(MESSAGES)


# --- Capabilities -----------------------------------------------------------------


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_supports_reads_models_yaml_flags(provider_cls):
    provider, _ = make_provider(provider_cls, lambda r: httpx2.Response(200, json=completion()))

    assert provider.supports("tools") is True
    assert provider.supports("json") is False  # null in models.yaml = not tested = no


# --- The interface ----------------------------------------------------------------


def test_a_provider_without_chat_cannot_be_created():
    class Incomplete(LLMProvider):
        name = "incomplete"

    with pytest.raises(TypeError):
        Incomplete({"id": "x"})


# --- FakeProvider -----------------------------------------------------------------


def test_fake_is_an_llm_provider():
    assert isinstance(FakeProvider(), LLMProvider)


def test_fake_returns_replies_in_order_then_repeats_the_last():
    fake = FakeProvider(replies=["first", "second"])

    texts = [fake.chat(MESSAGES).text for _ in range(3)]

    assert texts == ["first", "second", "second"]


def test_fake_records_what_it_was_asked():
    fake = FakeProvider()

    response = fake.chat(MESSAGES)

    assert fake.calls == [MESSAGES]
    assert response.provider == "fake"
    assert response.tokens_in == 3  # "What is photosynthesis?" -> 3 words


def test_fake_raises_the_error_it_was_given():
    fake = FakeProvider(error=RateLimitedError("slow down", "fake", retry_after=1))

    with pytest.raises(RateLimitedError):
        fake.chat(MESSAGES)


def test_fake_capabilities_can_be_configured():
    fake = FakeProvider(model_config={"id": "fake-no-tools", "supports_tools": False})

    assert fake.supports("tools") is False
    assert fake.model == "fake-no-tools"
