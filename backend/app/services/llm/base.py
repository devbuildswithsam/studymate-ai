"""The LLMProvider interface: one shape for every provider. SMA-21 (guide §7.5).

The rest of the app only talks to LLMProvider, so swapping Gemini for Groq
(or a fake in tests) never changes the calling code.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

Capability = Literal["tools", "json"]
# {"role": "system" | "user" | "assistant" | "tool", "content": "...", ...}. With tools, an
# assistant message also carries "tool_calls", and a tool message a "tool_call_id" (SMA-42).
Message = dict[str, Any]


@dataclass
class ChatOptions:
    temperature: float = 0.0
    max_tokens: int = 1024
    json_mode: bool = False  # ask the model to reply with a JSON object
    # MCP tools offered to the model, in the chat API's "functions" format (SMA-42).
    tools: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class ToolCall:
    """The model asking us to run a tool. It never runs anything itself."""

    id: str  # the result we send back must carry this id
    name: str
    arguments: str  # JSON text, exactly as the model wrote it (it may be broken)
    # Fields outside the OpenAI format, sent back unchanged: Gemini's thinking models
    # answer 400 without their "thought_signature" (found in SMA-39).
    extra: dict[str, Any] | None = None

    def as_message_part(self) -> dict[str, Any]:
        """This call as it goes back into the history, in the assistant message."""
        part = {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }
        return {**part, **(self.extra or {})}


@dataclass
class ChatResponse:
    """The same answer format, whichever provider answered."""

    text: str
    tokens_in: int
    tokens_out: int
    model: str
    provider: str
    latency_ms: int
    tool_calls: list[ToolCall] = field(default_factory=list)  # empty = a final answer
    stopped: bool = False  # SMA-62: the student pressed Stop; `text` is what arrived


@dataclass
class TextStream:
    """Where a streamed answer goes, piece by piece (SMA-62).

    The provider calls send() for every piece of text and asks should_stop() between
    pieces (the Stop button). `text` is everything sent so far for this answer.
    """

    on_text: Callable[[str], None]
    should_stop: Callable[[], bool] = lambda: False
    text: str = ""

    def send(self, piece: str) -> None:
        self.text += piece
        self.on_text(piece)


class LLMProvider(ABC):
    """One model from models.yaml, behind a common interface."""

    name: str  # provider name, e.g. "gemini"; set by each subclass

    def __init__(self, model_config: dict):
        # model_config is one entry from models.yaml: id, supports_tools, supports_json, ...
        self.model_config = model_config
        self.model = model_config["id"]

    def supports(self, capability: Capability) -> bool:
        # Read from models.yaml. null ("not tested yet") counts as no.
        return self.model_config.get(f"supports_{capability}") is True

    @abstractmethod
    def chat(self, messages: list[Message], options: ChatOptions | None = None) -> ChatResponse:
        """Send the conversation, get one answer back. Raises an LLMError subclass on failure."""

    def chat_stream(
        self, messages: list[Message], options: ChatOptions | None, stream: TextStream
    ) -> ChatResponse:
        """Like chat(), but the text goes to `stream` as it arrives (SMA-62).

        This default can't really stream: it waits for the whole answer and sends it in
        one piece. Providers that can stream (openai_compat.py, the fake) override it.
        """
        response = self.chat(messages, options)
        if response.text:
            stream.send(response.text)
        return response
