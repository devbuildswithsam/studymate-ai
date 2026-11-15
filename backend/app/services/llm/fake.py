"""FakeProvider: a pretend LLM for tests. SMA-21.

CLAUDE.md: tests never call real APIs. The fake answers instantly, costs nothing,
and can be told to fail, so we can test how the app handles errors.
"""

from app.services.llm.base import ChatOptions, ChatResponse, LLMProvider, Message


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(
        self,
        replies: list[str] | None = None,
        error: Exception | None = None,
        model_config: dict | None = None,
    ):
        super().__init__(
            model_config or {"id": "fake-model", "supports_tools": True, "supports_json": True}
        )
        self.replies = list(replies or ["This is a fake answer."])
        self.error = error  # if set, every chat() call raises it
        self.calls: list[list[Message]] = []  # what we were asked, so tests can check it

    def chat(self, messages: list[Message], options: ChatOptions | None = None) -> ChatResponse:
        self.calls.append(messages)
        if self.error:
            raise self.error
        # Replies are used in order; the last one repeats once the list runs out.
        text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return ChatResponse(
            text=text,
            tokens_in=sum(len(m["content"].split()) for m in messages),  # rough word count
            tokens_out=len(text.split()),
            model=self.model,
            provider=self.name,
            latency_ms=0,
        )
