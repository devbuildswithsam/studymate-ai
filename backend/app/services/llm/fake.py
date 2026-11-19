"""FakeProvider: a pretend LLM for tests. SMA-21.

CLAUDE.md: tests never call real APIs. The fake answers instantly, costs nothing,
and can be told to fail, so we can test how the app handles errors.
"""

import hashlib

from app.services.llm.base import ChatOptions, ChatResponse, LLMProvider, Message, ToolCall
from app.services.llm.embeddings import EmbeddingProvider
from app.services.llm.exceptions import ProviderUnavailableError
from app.services.llm.registry import EmbeddingConfig


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(
        self,
        # Each reply is a text answer, or a list of ToolCalls (asking for tools, SMA-42).
        replies: list[str | list[ToolCall]] | None = None,
        error: Exception | None = None,
        model_config: dict | None = None,
    ):
        super().__init__(
            model_config or {"id": "fake-model", "supports_tools": True, "supports_json": True}
        )
        self.replies = list(replies or ["This is a fake answer."])
        self.error = error  # if set, every chat() call raises it
        self.calls: list[list[Message]] = []  # what we were asked, so tests can check it
        self.options: list[ChatOptions] = []  # the options of each call (max_tokens, ...)

    def chat(self, messages: list[Message], options: ChatOptions | None = None) -> ChatResponse:
        self.calls.append(list(messages))  # a copy: the agent loop keeps appending to its list
        self.options.append(options or ChatOptions())
        if self.error:
            raise self.error
        # Replies are used in order; the last one repeats once the list runs out.
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        tool_calls = reply if isinstance(reply, list) else []
        text = "" if tool_calls else reply
        return ChatResponse(
            text=text,
            # a rough word count; a message asking for tools has no content (None)
            tokens_in=sum(len(str(m.get("content") or "").split()) for m in messages),
            tokens_out=len(text.split()),
            model=self.model,
            provider=self.name,
            latency_ms=0,
            tool_calls=tool_calls,
        )


class FakeEmbeddingProvider(EmbeddingProvider):
    """A pretend embedding model for tests (SMA-46). The same text always gets the same
    vector, so tests can compare results; it can fail on a chosen call, or return vectors
    of the wrong size, to test how ingestion handles that."""

    def __init__(
        self,
        dimensions: int = 8,
        batch_size: int = 50,
        model: str = "fake-embedding",
        version: int = 1,
        fail_on_call: int | None = None,  # 1 = the first embed() call raises `error`
        error: Exception | None = None,
        wrong_dimensions: int | None = None,  # answer with vectors of this size instead
    ):
        super().__init__(
            EmbeddingConfig(
                id=model,
                provider="fake",
                dimensions=dimensions,
                version=version,
                batch_size=batch_size,
            )
        )
        self.fail_on_call = fail_on_call
        # Like a real provider failure (adapters only raise LLMError types).
        self.error = error or ProviderUnavailableError("fake embedding failure", "fake")
        self.wrong_dimensions = wrong_dimensions
        self.batches: list[list[str]] = []  # every batch of texts we were asked to embed

    def _embed(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        if len(self.batches) == self.fail_on_call:
            raise self.error
        size = self.wrong_dimensions or self.dimensions
        return [_fake_vector(text, size) for text in texts]


def _fake_vector(text: str, size: int) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()  # same text -> same numbers
    return [digest[i % len(digest)] / 255 for i in range(size)]
