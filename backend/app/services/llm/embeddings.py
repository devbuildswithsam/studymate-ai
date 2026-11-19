"""Embedding providers: text -> float32 vectors (guide 7.5 "Provider abstraction"). SMA-46.

Separate from LLMProvider on purpose: there is NO fallback here. Vectors from two models
(or two sizes) can't be compared, so a document is embedded by one model or not at all;
on failure, ingestion stops and can be retried (app/services/rag/embed.py).
"""

from abc import ABC, abstractmethod
from array import array
from collections.abc import Callable
from typing import Annotated

import httpx2
import openai
from fastapi import Depends

from app.config import Settings, get_settings
from app.services.llm.exceptions import LLMConfigError, LLMError
from app.services.llm.gemini import GeminiProvider
from app.services.llm.openai_compat import OpenAICompatibleProvider
from app.services.llm.registry import EmbeddingConfig, ModelRegistry, api_key_for, get_registry

Vector = array  # array("f"): float32 numbers, exactly what chunks.embedding stores


class EmbeddingError(LLMError):
    """The provider answered, but not with what we asked for (wrong size, missing vector)."""


class EmbeddingProvider(ABC):
    def __init__(self, config: EmbeddingConfig):
        self.model = config.id
        self.provider = config.provider
        self.dimensions = config.dimensions
        self.version = config.version
        self.batch_size = config.batch_size

    def embed(self, texts: list[str]) -> list[Vector]:
        """One float32 vector per text, in the same order. Checked before anyone stores it."""
        vectors = self._embed(texts)
        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"{self.model} returned {len(vectors)} vectors for {len(texts)} texts",
                self.provider,
            )
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise EmbeddingError(
                    f"{self.model} returned a vector of {len(vector)} numbers instead of "
                    f"{self.dimensions}",
                    self.provider,
                )
        return [array("f", v) for v in vectors]

    @abstractmethod
    def _embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """Uses a chat adapter's client: same timeout, no hidden retries, same error types."""

    def __init__(self, config: EmbeddingConfig, adapter: OpenAICompatibleProvider):
        super().__init__(config)
        self.adapter = adapter

    def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            r = self.adapter.client.embeddings.create(
                model=self.model,
                input=texts,
                dimensions=self.dimensions,  # ask for the size we store (ADR-0008)
                encoding_format="float",
            )
        except openai.OpenAIError as e:
            raise self.adapter.translate_error(e) from e
        # Match vectors to texts by "index", never by position in the reply. Gemini leaves
        # out index 0 (Google's APIs omit fields equal to their default, seen live): a
        # missing index means 0.
        by_index = {d.index or 0: d.embedding for d in r.data}
        if sorted(by_index) != list(range(len(r.data))):
            raise EmbeddingError(
                f"{self.model} returned vectors with unexpected index numbers "
                f"{sorted(by_index)}",
                self.provider,
            )
        return [by_index[i] for i in range(len(by_index))]


class GeminiEmbeddingProvider(OpenAICompatibleEmbeddingProvider):
    def __init__(
        self,
        config: EmbeddingConfig,
        api_key: str,
        base_url: str,
        http_client: httpx2.Client | None = None,  # tests pass a fake server here
    ):
        # The Gemini adapter brings Gemini's error quirks (a bad key is HTTP 400).
        adapter = GeminiProvider(
            {"id": config.id}, api_key=api_key, base_url=base_url, http_client=http_client
        )
        super().__init__(config, adapter)


EMBEDDING_ADAPTERS = {"gemini": GeminiEmbeddingProvider}


def build_embedding_provider(registry: ModelRegistry, settings: Settings) -> EmbeddingProvider:
    config = registry.embeddings
    if config is None:
        raise LLMConfigError("models.yaml has no embeddings section", "embeddings")
    adapter = EMBEDDING_ADAPTERS.get(config.provider)
    if adapter is None:
        raise LLMConfigError(f"no embedding adapter for {config.provider!r}", config.provider)
    api_key = api_key_for(registry, config.provider, settings)
    if not api_key:
        env_name = registry.providers[config.provider].api_key_env
        raise LLMConfigError(f"{env_name} is not set in backend/.env", config.provider)
    return adapter(config, api_key=api_key, base_url=registry.providers[config.provider].base_url)


def get_embedder(
    registry: Annotated[ModelRegistry, Depends(get_registry)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Callable[[], EmbeddingProvider]:
    """FastAPI dependency: a function that builds the provider WHEN it's needed, inside the
    route's own error handling (a missing key must fail the document, not the request).
    Tests replace it with a fake."""
    return lambda: build_embedding_provider(registry, settings)
