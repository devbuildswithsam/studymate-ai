"""FakeProvider: a pretend LLM for tests. SMA-21.

CLAUDE.md: tests never call real APIs. The fake answers instantly, costs nothing,
and can be told to fail, so we can test how the app handles errors.
"""

from app.services.llm.base import ChatOptions, ChatResponse, LLMProvider, Message, ToolCall


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
