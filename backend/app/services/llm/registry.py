"""Load and validate the model registry (models.yaml). SMA-17, validated with Pydantic in SMA-22.

models.yaml is the ONLY place model ids live. A mistake in it (a typo'd field, a
model pointing at a provider that doesn't exist) stops the app at startup with a
clear message, instead of failing on the first chat request.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

import openai
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.config import Settings, get_settings
from app.services.llm.base import Capability

REGISTRY_PATH = Path(__file__).with_name("models.yaml")


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown field = typo = error

    base_url: str
    api_key_env: str  # the NAME of the setting holding the key, e.g. GEMINI_API_KEY


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    provider: str
    display_name: str
    priority: int  # lower = tried first
    context_window: int | None = None
    supports_tools: bool | None = None  # None = not tested yet, treated as "no"
    supports_json: bool | None = None
    default_for: list[Literal["chat", "study", "quiz"]] = []
    enabled: bool = True

    def supports(self, capability: Capability) -> bool:
        return getattr(self, f"supports_{capability}") is True


class ModelRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    providers: dict[str, ProviderConfig]
    models: list[ModelConfig]

    @model_validator(mode="after")
    def check_models_fit_together(self) -> "ModelRegistry":
        ids = [m.id for m in self.models]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate model ids: {sorted({i for i in ids if ids.count(i) > 1})}")
        priorities = [m.priority for m in self.models]
        if len(priorities) != len(set(priorities)):
            raise ValueError("two models share a priority, so the fallback order is unclear")
        for m in self.models:
            if m.provider not in self.providers:
                raise ValueError(f"model {m.id!r} uses unknown provider {m.provider!r}")
        if not any(m.enabled for m in self.models):
            raise ValueError("no model is enabled")
        return self

    def enabled_models(self) -> list[ModelConfig]:
        """Enabled models, in the order they should be tried."""
        return sorted((m for m in self.models if m.enabled), key=lambda m: m.priority)

    def get(self, model_id: str) -> ModelConfig:
        for m in self.models:
            if m.id == model_id:
                return m
        raise KeyError(f"unknown model id {model_id!r} (not in models.yaml)")


def load_registry(path: Path = REGISTRY_PATH) -> ModelRegistry:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    try:
        return ModelRegistry.model_validate(data)
    except ValidationError as e:
        # Name the file, so the startup error says where to look.
        raise ValueError(f"{path.name} is invalid:\n{e}") from e


@lru_cache
def get_registry() -> ModelRegistry:
    """Load models.yaml once and reuse it (also used as a FastAPI dependency)."""
    return load_registry()


def api_key_for(registry: ModelRegistry, provider: str, settings: Settings) -> str | None:
    """The provider's API key from settings (backend/.env), or None if it isn't set."""
    # api_key_env "GEMINI_API_KEY" -> Settings field gemini_api_key
    secret = getattr(settings, registry.providers[provider].api_key_env.lower(), None)
    return secret.get_secret_value() if secret else None


def client_for(registry: ModelRegistry, provider: str, max_retries: int = 2) -> openai.OpenAI:
    """A raw OpenAI-compatible client, for the dev scripts in scripts/.

    The app itself uses the adapters (factory.py) instead.
    """
    api_key = api_key_for(registry, provider, get_settings())
    if not api_key:
        raise RuntimeError(f"Missing {registry.providers[provider].api_key_env} in backend/.env")
    cfg = registry.providers[provider]
    return openai.OpenAI(
        base_url=cfg.base_url, api_key=api_key, timeout=60, max_retries=max_retries
    )
