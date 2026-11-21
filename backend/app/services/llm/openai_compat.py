"""Shared code for providers that speak the OpenAI-compatible Chat Completions API. SMA-21.

GeminiProvider and GroqProvider build on this; each overrides only what differs.
"""

import time

import httpx2
import openai

from app.services.llm.base import (
    ChatOptions,
    ChatResponse,
    LLMProvider,
    Message,
    TextStream,
    ToolCall,
)
from app.services.llm.exceptions import (
    LLMConfigError,
    LLMError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitedError,
)

STANDARD_TOOL_CALL_FIELDS = {"id", "type", "function", "index"}


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        model_config: dict,
        api_key: str,
        base_url: str,
        timeout: float = 60,
        http_client: httpx2.Client | None = None,  # tests pass a fake server here
    ):
        super().__init__(model_config)
        # max_retries=0: the SDK would otherwise retry silently, hiding 429s and slowing
        # fallback. Deciding to retry or switch provider is the FallbackManager's job (SMA-22).
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
            http_client=http_client,
        )

    @staticmethod
    def _extra(options: ChatOptions) -> dict:
        """Request fields that only some calls need."""
        extra = {"response_format": {"type": "json_object"}} if options.json_mode else {}
        if options.tools:
            extra["tools"] = options.tools  # SMA-42: the model may answer with tool calls
        return extra

    def chat(self, messages: list[Message], options: ChatOptions | None = None) -> ChatResponse:
        options = options or ChatOptions()
        extra = self._extra(options)

        start = time.perf_counter()
        try:
            r = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=options.temperature,
                max_tokens=options.max_tokens,
                **extra,
            )
        except openai.OpenAIError as e:
            raise self.translate_error(e) from e
        latency_ms = round((time.perf_counter() - start) * 1000)

        choice = r.choices[0]
        tool_calls = self._tool_calls(choice.message)
        if not choice.message.content and not tool_calls:
            # e.g. a safety block: no text, only a finish_reason. Never show a blank answer.
            # (No text is normal when the model asks for tools instead.)
            raise LLMError(
                f"{self.name} returned an empty answer (finish_reason={choice.finish_reason})",
                self.name,
            )
        return ChatResponse(
            text=choice.message.content or "",
            tool_calls=tool_calls,
            tokens_in=r.usage.prompt_tokens if r.usage else 0,
            tokens_out=r.usage.completion_tokens if r.usage else 0,
            model=self.model,
            provider=self.name,
            latency_ms=latency_ms,
        )

    def chat_stream(
        self, messages: list[Message], options: ChatOptions | None, stream: TextStream
    ) -> ChatResponse:
        """The answer as it is written (SMA-62): stream=True makes the provider send small
        "chunks" (Server-Sent Events). Text goes to `stream` at once; tool calls arrive in
        pieces too (name first, then bits of the arguments) and are put back together."""
        options = options or ChatOptions()
        start = time.perf_counter()
        text = ""
        tool_parts: dict[int, dict] = {}  # tool call index -> its pieces so far
        usage = None
        finish_reason = None
        stopped = False
        try:
            chunks = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=options.temperature,
                max_tokens=options.max_tokens,
                stream=True,
                stream_options={"include_usage": True},  # token counts in the last chunk
                **self._extra(options),
            )
            with chunks:  # closes the connection when we stop early: no more tokens billed
                for chunk in chunks:
                    if chunk.usage:
                        usage = chunk.usage
                    for choice in chunk.choices[:1]:
                        for call in choice.delta.tool_calls or []:
                            self._add_tool_piece(tool_parts, call)
                        if choice.delta.content:
                            text += choice.delta.content
                            stream.send(choice.delta.content)
                        finish_reason = choice.finish_reason or finish_reason
                    if stream.should_stop():  # the Stop button
                        stopped = True
                        break
        except openai.OpenAIError as e:
            raise self.translate_error(e) from e
        except httpx2.HTTPError as e:  # the connection dropped halfway through the answer
            raise ProviderUnavailableError(
                f"{self.name}: the connection was lost mid-answer", self.name
            ) from e

        tool_calls = [
            ToolCall(p["id"], p["name"], p["arguments"], p["extra"] or None)
            for _, p in sorted(tool_parts.items())
        ]
        if not text and not tool_calls and not stopped:
            raise LLMError(
                f"{self.name} returned an empty answer (finish_reason={finish_reason})", self.name
            )
        return ChatResponse(
            text=text,
            tool_calls=tool_calls,
            tokens_in=usage.prompt_tokens if usage else 0,
            tokens_out=usage.completion_tokens if usage else 0,
            model=self.model,
            provider=self.name,
            latency_ms=round((time.perf_counter() - start) * 1000),
            stopped=stopped,
        )

    @staticmethod
    def _add_tool_piece(parts: dict[int, dict], call) -> None:
        """Add one streamed piece of a tool call to what we have so far."""
        part = parts.setdefault(call.index, {"id": "", "name": "", "arguments": "", "extra": {}})
        if call.id:
            part["id"] = call.id
        if call.function and call.function.name:
            part["name"] += call.function.name
        if call.function and call.function.arguments:
            part["arguments"] += call.function.arguments
        raw = call.model_dump(exclude_none=True)  # provider extras (Gemini's signatures)
        part["extra"].update({k: v for k, v in raw.items() if k not in STANDARD_TOOL_CALL_FIELDS})

    @staticmethod
    def _tool_calls(message) -> list[ToolCall]:
        """The tool calls in a reply, with any provider-specific extra fields kept."""
        calls = []
        for call in message.tool_calls or []:
            raw = call.model_dump(exclude_none=True)  # includes fields the SDK doesn't know
            extra = {k: v for k, v in raw.items() if k not in STANDARD_TOOL_CALL_FIELDS}
            calls.append(
                ToolCall(call.id, call.function.name, call.function.arguments, extra or None)
            )
        return calls

    def translate_error(self, e: openai.OpenAIError) -> LLMError:
        """Any SDK error -> one of our types. Public: the embedding provider (SMA-46) sends
        its requests through this adapter's client and reuses this too."""
        if isinstance(e, openai.APITimeoutError):  # before APIConnectionError: a subclass
            return ProviderTimeoutError(f"{self.name} timed out", self.name)
        if isinstance(e, openai.APIConnectionError):
            return ProviderUnavailableError(f"Could not reach {self.name}", self.name)
        if isinstance(e, openai.APIStatusError):
            return self._error_from_status(e)  # subclasses add quirks (Gemini's 400 key)
        return LLMError(f"{self.name}: {e}", self.name)

    def _error_from_status(self, e: openai.APIStatusError) -> LLMError:
        """Turn an HTTP error into one of our types (CLAUDE.md: 404 fix config,
        429 wait/fallback, 503 retry/fallback)."""
        status = e.status_code
        message = f"{self.name} HTTP {status}: {self._error_message(e)}"
        if status == 429:
            return RateLimitedError(message, self.name, retry_after=self._retry_after(e))
        if status in (401, 403, 404):
            return LLMConfigError(message, self.name, status)
        if status >= 500:
            return ProviderUnavailableError(message, self.name, status)
        return LLMError(message, self.name, status)

    @staticmethod
    def _error_message(e: openai.APIStatusError) -> str:
        """The provider's own explanation, which is usually the most useful part."""
        body = e.body
        if isinstance(body, list) and body:  # some providers wrap the error in a list
            body = body[0]
        if isinstance(body, dict):
            body = body.get("error", body)
            if isinstance(body, dict) and body.get("message"):
                return str(body["message"])
        return str(e.message)

    @staticmethod
    def _retry_after(e: openai.APIStatusError) -> float | None:
        """Seconds to wait, from the standard Retry-After header (if sent)."""
        try:
            return float(e.response.headers["retry-after"])
        except (KeyError, ValueError):
            return None
