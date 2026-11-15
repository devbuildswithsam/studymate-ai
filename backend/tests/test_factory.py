"""Tests for build_provider: models.yaml entry -> ready adapter. SMA-23 (fills an SMA-22 gap)."""

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.services.llm.exceptions import LLMConfigError
from app.services.llm.factory import build_provider
from app.services.llm.gemini import GeminiProvider
from app.services.llm.groq import GroqProvider
from app.services.llm.registry import ModelRegistry

REGISTRY = ModelRegistry.model_validate(
    {
        "version": 1,
        "providers": {
            "gemini": {"base_url": "https://g.test/v1/", "api_key_env": "GEMINI_API_KEY"},
            "groq": {"base_url": "https://q.test/v1/", "api_key_env": "GROQ_API_KEY"},
            "mystery": {"base_url": "https://m.test/v1/", "api_key_env": "GROQ_API_KEY"},
        },
        "models": [
            {
                "id": "g",
                "provider": "gemini",
                "display_name": "G",
                "priority": 1,
                "supports_tools": True,
            },
            {"id": "q", "provider": "groq", "display_name": "Q", "priority": 2},
            {"id": "m", "provider": "mystery", "display_name": "M", "priority": 3},
        ],
    }
)


def settings(gemini: str | None = "test-gemini-key", groq: str | None = "test-groq-key"):
    return Settings(
        _env_file=None,
        env="test",
        gemini_api_key=SecretStr(gemini) if gemini is not None else None,
        groq_api_key=SecretStr(groq) if groq is not None else None,
    )


@pytest.mark.parametrize(
    "model_id, adapter, key, url",
    [
        ("g", GeminiProvider, "test-gemini-key", "https://g.test/v1/"),
        ("q", GroqProvider, "test-groq-key", "https://q.test/v1/"),
    ],
)
def test_builds_the_right_adapter_with_its_key_and_url(model_id, adapter, key, url):
    provider = build_provider(REGISTRY.get(model_id), REGISTRY, settings())

    assert type(provider) is adapter
    assert provider.model == model_id
    assert provider.client.api_key == key
    assert str(provider.client.base_url) == url


def test_the_adapter_gets_the_models_capabilities():
    provider = build_provider(REGISTRY.get("g"), REGISTRY, settings())

    assert provider.supports("tools") is True
    assert provider.supports("json") is False


def test_missing_key_is_a_config_error_naming_the_setting():
    with pytest.raises(LLMConfigError, match="GROQ_API_KEY is not set"):
        build_provider(REGISTRY.get("q"), REGISTRY, settings(groq=None))


def test_empty_key_counts_as_missing():
    # .env.example has `GEMINI_API_KEY=` (empty): that must not be sent as a key.
    with pytest.raises(LLMConfigError, match="GEMINI_API_KEY is not set"):
        build_provider(REGISTRY.get("g"), REGISTRY, settings(gemini=""))


def test_provider_without_an_adapter_is_a_config_error():
    with pytest.raises(LLMConfigError, match="no adapter for provider 'mystery'"):
        build_provider(REGISTRY.get("m"), REGISTRY, settings())
