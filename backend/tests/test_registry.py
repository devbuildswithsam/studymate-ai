"""Tests for loading and validating models.yaml. SMA-22."""

import copy

import pytest
from pydantic import ValidationError

from app.services.llm.registry import ModelRegistry, load_registry

VALID = {
    "version": 1,
    "providers": {"gemini": {"base_url": "https://g.test/v1", "api_key_env": "GEMINI_API_KEY"}},
    "models": [
        {"id": "a", "provider": "gemini", "display_name": "A", "priority": 1},
        {"id": "b", "provider": "gemini", "display_name": "B", "priority": 2, "enabled": False},
    ],
}


def registry_with(change) -> dict:
    """A copy of VALID with one change applied, so each test breaks exactly one thing."""
    data = copy.deepcopy(VALID)
    change(data)
    return data


def test_the_real_models_yaml_is_valid():
    registry = load_registry()

    assert registry.enabled_models(), "at least one model must be enabled"


def test_the_real_chat_default_can_use_tools_and_is_tried_first():
    # SMA-42: chat messages may use MCP tools, so the default model must support them.
    registry = load_registry()
    default = registry.default_model("chat")

    assert registry.get(default).supports("tools")
    assert registry.enabled_models()[0].id == default  # first in the fallback order


def test_enabled_models_are_sorted_by_priority_and_skip_disabled():
    data = registry_with(lambda d: d["models"][1].update(enabled=True, priority=0))

    assert [m.id for m in ModelRegistry.model_validate(data).enabled_models()] == ["b", "a"]
    assert [m.id for m in ModelRegistry.model_validate(VALID).enabled_models()] == ["a"]


def test_null_capability_counts_as_unsupported():
    registry = ModelRegistry.model_validate(
        registry_with(lambda d: d["models"][0].update(supports_tools=True, supports_json=None))
    )

    assert registry.get("a").supports("tools") is True
    assert registry.get("a").supports("json") is False


@pytest.mark.parametrize(
    "change, expected_error",
    [
        (lambda d: d["models"][0].update(priorty=3), "Extra inputs are not permitted"),
        (lambda d: d["models"][0].update(provider="openrouter"), "unknown provider"),
        (lambda d: d["models"][1].update(id="a"), "duplicate model ids"),
        (lambda d: d["models"][1].update(priority=1), "share a priority"),
        (lambda d: d["models"][0].update(enabled=False), "no model is enabled"),
        (lambda d: d["models"][0].update(default_for=["chatt"]), "default_for"),
        (lambda d: d["models"][0].pop("display_name"), "Field required"),
    ],
    ids=[
        "typo",
        "unknown-provider",
        "duplicate-id",
        "same-priority",
        "none-enabled",
        "bad-default-for",
        "missing-field",
    ],
)
def test_bad_registry_is_rejected(change, expected_error):
    with pytest.raises(ValidationError, match=expected_error):
        ModelRegistry.model_validate(registry_with(change))


def test_load_registry_names_the_file_in_the_error(tmp_path):
    bad = tmp_path / "models.yaml"
    bad.write_text("version: 1\nproviders: {}\nmodels: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="models.yaml is invalid"):
        load_registry(bad)


def test_get_unknown_model_raises_key_error():
    with pytest.raises(KeyError, match="not in models.yaml"):
        ModelRegistry.model_validate(VALID).get("nope")
