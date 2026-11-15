"""The LLMProvider interface: one shape for every provider. SMA-21 (guide §7.5).

The rest of the app only talks to LLMProvider, so swapping Gemini for Groq
(or a fake in tests) never changes the calling code.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

Capability = Literal["tools", "json"]
Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": "..."}


@dataclass
class ChatOptions:
    temperature: float = 0.0
    max_tokens: int = 1024
    json_mode: bool = False  # ask the model to reply with a JSON object


@dataclass
class ChatResponse:
    """The same answer format, whichever provider answered."""

    text: str
    tokens_in: int
    tokens_out: int
    model: str
    provider: str
    latency_ms: int


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
