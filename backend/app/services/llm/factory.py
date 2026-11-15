"""Build the right adapter for a model from models.yaml. SMA-22.

A factory: callers say *which model*, and get a ready LLMProvider back without
knowing which class, key or URL it needs.
"""

from app.config import Settings
from app.services.llm.base import LLMProvider
from app.services.llm.exceptions import LLMConfigError
from app.services.llm.gemini import GeminiProvider
from app.services.llm.groq import GroqProvider
from app.services.llm.registry import ModelConfig, ModelRegistry, api_key_for

# Provider name in models.yaml -> the adapter class that speaks to it.
ADAPTERS: dict[str, type[GeminiProvider | GroqProvider]] = {
    "gemini": GeminiProvider,
    "groq": GroqProvider,
}


def build_provider(model: ModelConfig, registry: ModelRegistry, settings: Settings) -> LLMProvider:
    adapter = ADAPTERS.get(model.provider)
    if adapter is None:
        raise LLMConfigError(f"no adapter for provider {model.provider!r}", model.provider)

    api_key = api_key_for(registry, model.provider, settings)
    if not api_key:
        env_name = registry.providers[model.provider].api_key_env
        raise LLMConfigError(f"{env_name} is not set in backend/.env", model.provider)

    return adapter(
        model.model_dump(),  # the adapters take the model's settings as a plain dict
        api_key=api_key,
        base_url=registry.providers[model.provider].base_url,
    )
