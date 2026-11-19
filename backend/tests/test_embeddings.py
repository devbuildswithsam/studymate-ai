"""Embedding providers (guide: EmbeddingProvider, separate from LLMProvider). SMA-46.

No real API is called: httpx2.MockTransport plays Gemini's OpenAI-compatible server.
"""

import json
from array import array

import httpx2
import pytest

from app.services.llm.embeddings import (
    EmbeddingError,
    GeminiEmbeddingProvider,
    build_embedding_provider,
)
from app.services.llm.exceptions import (
    LLMConfigError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.services.llm.fake import FakeEmbeddingProvider
from app.services.llm.registry import EmbeddingConfig, ModelRegistry

CONFIG = EmbeddingConfig(id="embed-model", provider="gemini", dimensions=4, version=1, batch_size=2)


def embeddings_response(vectors: list[list[float]]) -> dict:
    return {
        "object": "list",
        "model": "embed-model",
        "data": [
            {"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)
        ],
        "usage": {"prompt_tokens": 5, "total_tokens": 5},
    }


def make_provider(respond):
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return respond(request)

    provider = GeminiEmbeddingProvider(
        CONFIG,
        api_key="test-key",
        base_url="https://llm.example.test/v1",
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return provider, sent


def answer(vectors, status=200):
    return lambda request: httpx2.Response(status, json=embeddings_response(vectors))


# --- GeminiEmbeddingProvider ---------------------------------------------------------------


def test_texts_become_float32_vectors_in_order():
    provider, sent = make_provider(answer([[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]))

    vectors = provider.embed(["first text", "second text"])

    assert all(isinstance(v, array) and v.typecode == "f" for v in vectors)  # float32
    assert [round(x, 2) for x in vectors[1]] == [0.5, 0.6, 0.7, 0.8]
    body = json.loads(sent[0].content)
    assert body == {
        "model": "embed-model",
        "input": ["first text", "second text"],
        "dimensions": 4,  # the size we store, asked for explicitly
        "encoding_format": "float",
    }


def test_vectors_are_matched_to_texts_by_index_not_by_position():
    def respond(request):
        data = embeddings_response([[1, 1, 1, 1], [2, 2, 2, 2]])
        data["data"].reverse()  # the API may answer in any order: "index" says which is which
        return httpx2.Response(200, json=data)

    provider, _ = make_provider(respond)

    assert [v[0] for v in provider.embed(["a", "b"])] == [1.0, 2.0]


def test_gemini_leaves_out_index_0_and_that_still_works():
    # Seen live (SMA-46): Google's APIs omit fields equal to their default, so the first
    # item arrives with no "index" at all.
    def respond(request):
        data = embeddings_response([[0, 0, 0, 0], [1, 1, 1, 1], [2, 2, 2, 2]])
        del data["data"][0]["index"]
        return httpx2.Response(200, json=data)

    provider, _ = make_provider(respond)

    assert [v[0] for v in provider.embed(["a", "b", "c"])] == [0.0, 1.0, 2.0]


def test_indexes_that_dont_match_the_texts_are_rejected():
    def respond(request):
        data = embeddings_response([[1, 1, 1, 1], [2, 2, 2, 2]])
        data["data"][1]["index"] = 5  # no text 5 was sent
        return httpx2.Response(200, json=data)

    provider, _ = make_provider(respond)

    with pytest.raises(EmbeddingError, match="index"):
        provider.embed(["a", "b"])


def test_a_vector_of_the_wrong_length_is_rejected():
    provider, _ = make_provider(answer([[0.1, 0.2, 0.3]]))  # 3 numbers, not 4

    with pytest.raises(EmbeddingError, match="3 numbers instead of 4"):
        provider.embed(["text"])


def test_a_missing_vector_is_rejected():
    provider, _ = make_provider(answer([[0.1, 0.2, 0.3, 0.4]]))  # 1 vector for 2 texts

    with pytest.raises(EmbeddingError, match="1 vectors for 2 texts"):
        provider.embed(["a", "b"])


@pytest.mark.parametrize(
    "status, error",
    [
        (429, RateLimitedError),  # free-tier quota: wait, then retry
        (503, ProviderUnavailableError),
        (404, LLMConfigError),  # wrong model id: fix models.yaml
    ],
)
def test_http_errors_become_our_error_types(status, error):
    provider, _ = make_provider(
        lambda request: httpx2.Response(status, json={"error": {"message": "nope"}})
    )

    with pytest.raises(error):
        provider.embed(["text"])


def test_a_timeout_becomes_a_timeout_error():
    def respond(request):
        raise httpx2.ReadTimeout("slow", request=request)

    provider, _ = make_provider(respond)

    with pytest.raises(ProviderTimeoutError):
        provider.embed(["text"])


# --- Building it from models.yaml -------------------------------------------------------------


def registry(embeddings: dict | None) -> ModelRegistry:
    return ModelRegistry.model_validate(
        {
            "version": 1,
            "providers": {
                "gemini": {"base_url": "https://g.test/v1", "api_key_env": "GEMINI_API_KEY"}
            },
            "models": [{"id": "chat", "provider": "gemini", "display_name": "Chat", "priority": 1}],
            "embeddings": embeddings,
        }
    )


class Settings:
    def __init__(self, key: str | None):
        from pydantic import SecretStr

        self.gemini_api_key = SecretStr(key) if key else None


def test_the_provider_is_built_from_models_yaml():
    provider = build_embedding_provider(registry(CONFIG.model_dump()), Settings("k"))

    assert (provider.model, provider.dimensions, provider.version) == ("embed-model", 4, 1)


def test_no_key_is_a_config_error():
    with pytest.raises(LLMConfigError, match="GEMINI_API_KEY"):
        build_embedding_provider(registry(CONFIG.model_dump()), Settings(None))


def test_no_embeddings_section_is_a_config_error():
    with pytest.raises(LLMConfigError, match="embeddings"):
        build_embedding_provider(registry(None), Settings("k"))


# --- The fake used by other tests ------------------------------------------------------------


def test_the_fake_gives_the_same_vector_for_the_same_text():
    fake = FakeEmbeddingProvider(dimensions=8)

    first, again, other = fake.embed(["heat", "heat", "work"])

    assert first == again != other
    assert len(first) == 8
    assert fake.batches == [["heat", "heat", "work"]]


def test_the_fake_can_fail_on_a_chosen_call():
    fake = FakeEmbeddingProvider(fail_on_call=2, error=RateLimitedError("quota", "fake"))

    fake.embed(["a"])
    with pytest.raises(RateLimitedError):
        fake.embed(["b"])
    fake.embed(["c"])  # and works again afterwards (for retry tests)
