"""Tests for GET /api/models. SMA-22."""

import pytest
from pydantic import SecretStr

from app.config import Settings, get_settings
from app.main import app
from app.services.llm.exceptions import RateLimitedError
from app.services.llm.fake import FakeProvider
from app.services.llm.fallback import FallbackManager, get_fallback_manager
from app.services.llm.registry import ModelRegistry, get_registry

REGISTRY = ModelRegistry.model_validate(
    {
        "version": 1,
        "providers": {
            "gemini": {"base_url": "https://g.test/v1", "api_key_env": "GEMINI_API_KEY"},
            "groq": {"base_url": "https://q.test/v1", "api_key_env": "GROQ_API_KEY"},
        },
        "models": [
            {
                "id": "g-main",
                "provider": "gemini",
                "display_name": "G Main",
                "priority": 1,
                "supports_tools": True,
                "supports_json": True,
                "default_for": ["chat"],
            },
            {
                "id": "g-busy",
                "provider": "gemini",
                "display_name": "G Busy",
                "priority": 2,
                "supports_tools": True,
                "supports_json": None,
            },
            {"id": "q-fast", "provider": "groq", "display_name": "Q Fast", "priority": 3},
            {
                "id": "g-off",
                "provider": "gemini",
                "display_name": "G Off",
                "priority": 4,
                "enabled": False,
            },
        ],
    }
)
FAKE_KEY = "fake-gemini-key-for-tests"


@pytest.fixture
def models_client(client):
    """The test client, with a Gemini key but no Groq key, and g-busy rate-limited."""
    fakes = {"g-main": FakeProvider(), "g-busy": FakeProvider(error=RateLimitedError("", "gemini"))}
    manager = FallbackManager(REGISTRY, lambda m: fakes[m.id])
    manager.chat([{"role": "user", "content": "hi"}], model_id="g-busy")  # g-busy 429s

    app.dependency_overrides[get_registry] = lambda: REGISTRY
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, env="test", gemini_api_key=SecretStr(FAKE_KEY), groq_api_key=None
    )
    app.dependency_overrides[get_fallback_manager] = lambda: manager
    return client


def test_lists_enabled_models_with_their_status(models_client):
    response = models_client.get("/api/models")

    assert response.status_code == 200
    body = response.json()
    assert body["default_model"] == "g-main"
    assert [(m["id"], m["status"]) for m in body["models"]] == [
        ("g-main", "available"),
        ("g-busy", "rate_limited"),  # recent 429
        ("q-fast", "no_key"),  # GROQ_API_KEY not set
    ]


def test_shows_capabilities_and_display_names(models_client):
    first, second, _ = models_client.get("/api/models").json()["models"]

    assert first == {
        "id": "g-main",
        "provider": "gemini",
        "display_name": "G Main",
        "supports_tools": True,
        "supports_json": True,
        "status": "available",
    }
    assert second["supports_json"] is False  # null in the registry = no


def test_never_returns_api_keys(models_client):
    response = models_client.get("/api/models")

    assert FAKE_KEY not in response.text
    assert "api_key" not in response.text
