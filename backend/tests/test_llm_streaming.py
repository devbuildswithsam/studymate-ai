"""Streaming answers in the LLM layer: providers and the fallback manager. SMA-62.

A TextStream receives the answer piece by piece. Fallback still works before the first
piece; after it, a failure keeps what arrived (AnswerInterruptedError) instead of mixing
two models' answers. Written test-first; no real API is called.
"""

import json

import httpx2
import pytest

from app.services.llm.base import ChatOptions, ChatResponse, LLMProvider, TextStream, ToolCall
from app.services.llm.exceptions import (
    AllModelsFailedError,
    AnswerInterruptedError,
    ProviderUnavailableError,
)
from app.services.llm.fake import FakeProvider
from app.services.llm.fallback import FallbackManager
from app.services.llm.groq import GroqProvider
from app.services.llm.registry import ModelRegistry

MESSAGES = [{"role": "user", "content": "What is entropy?"}]


def collect(should_stop=lambda: False) -> tuple[TextStream, list[str]]:
    pieces: list[str] = []
    return TextStream(on_text=pieces.append, should_stop=should_stop), pieces


# --- The fake provider streams word by word ------------------------------------------------


def test_the_fake_streams_its_reply_in_pieces():
    stream, pieces = collect()

    response = FakeProvider(replies=["Entropy measures disorder."]).chat_stream(
        MESSAGES, None, stream
    )

    assert pieces == ["Entropy ", "measures ", "disorder."]
    assert response.text == stream.text == "Entropy measures disorder."
    assert response.stopped is False


def test_stopping_keeps_what_arrived():
    stream, pieces = collect()
    stream.should_stop = lambda: len(pieces) >= 2

    response = FakeProvider(replies=["one two three four"]).chat_stream(MESSAGES, None, stream)

    assert response.text == "one two "
    assert response.stopped is True


def test_the_fake_can_fail_after_some_pieces():
    stream, pieces = collect()
    fake = FakeProvider(replies=["one two three"], fail_after_pieces=2)

    with pytest.raises(ProviderUnavailableError):
        fake.chat_stream(MESSAGES, None, stream)
    assert pieces == ["one ", "two "]


def test_a_provider_without_real_streaming_sends_its_answer_in_one_piece():
    class OnlyChat(LLMProvider):
        name = "only-chat"

        def chat(self, messages, options=None) -> ChatResponse:
            return ChatResponse("Whole answer.", 1, 2, self.model, self.name, 0)

    stream, pieces = collect()
    response = OnlyChat({"id": "m"}).chat_stream(MESSAGES, None, stream)

    assert pieces == ["Whole answer."] and response.text == "Whole answer."


# --- The fallback manager ---------------------------------------------------------------------

REGISTRY = ModelRegistry.model_validate(
    {
        "version": 1,
        "providers": {"p": {"base_url": "https://p.test/v1", "api_key_env": "P_KEY"}},
        "models": [
            {"id": "main", "provider": "p", "display_name": "Main", "priority": 1},
            {"id": "backup", "provider": "p", "display_name": "Backup", "priority": 2},
        ],
    }
)


def manager(main: FakeProvider, backup: FakeProvider) -> FallbackManager:
    fakes = {"main": main, "backup": backup}
    return FallbackManager(REGISTRY, lambda model: fakes[model.id])


def test_a_failure_before_the_first_piece_still_falls_back():
    stream, pieces = collect()
    broken = FakeProvider(error=ProviderUnavailableError("down", "fake"))

    result = manager(broken, FakeProvider(replies=["Backup answer."])).chat(
        MESSAGES, model_id="main", stream=stream
    )

    assert result.fallback_used is True
    assert "".join(pieces) == result.response.text == "Backup answer."


def test_a_failure_after_the_first_piece_keeps_the_partial_answer_and_does_not_fall_back():
    stream, pieces = collect()
    flaky = FakeProvider(replies=["one two three"], fail_after_pieces=2)
    backup = FakeProvider(replies=["Backup answer."])

    with pytest.raises(AnswerInterruptedError) as caught:
        manager(flaky, backup).chat(MESSAGES, model_id="main", stream=stream)

    assert caught.value.partial_text == "one two "
    assert [a.status for a in caught.value.attempts] == ["error"]  # logged
    assert backup.calls == []  # two models' answers are never mixed


def test_a_stopped_answer_is_an_ok_call_marked_stopped():
    stream, pieces = collect()
    stream.should_stop = lambda: len(pieces) >= 1

    result = manager(FakeProvider(replies=["one two"]), FakeProvider()).chat(
        MESSAGES, model_id="main", stream=stream
    )

    assert result.response.stopped is True
    assert [a.status for a in result.attempts] == ["ok"]


def test_without_a_stream_nothing_changes():
    result = manager(FakeProvider(replies=["Plain."]), FakeProvider()).chat(
        MESSAGES, model_id="main"
    )

    assert result.response.text == "Plain." and result.response.stopped is False


def test_every_model_failing_before_a_piece_is_still_all_models_failed():
    broken = FakeProvider(error=ProviderUnavailableError("down", "fake"))
    stream, _ = collect()

    with pytest.raises(AllModelsFailedError):
        manager(broken, broken).chat(MESSAGES, model_id="main", stream=stream)


# --- The real OpenAI-compatible adapter (HTTP mocked: the provider's server is faked) --------


def sse(*events: dict, done: bool = True) -> bytes:
    """A streamed Chat Completions answer, as the provider sends it (Server-Sent Events)."""
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    return (body + ("data: [DONE]\n\n" if done else "")).encode()


def chunk(content=None, tool_calls=None, finish_reason=None, usage=None) -> dict:
    delta = {}
    if content is not None:
        delta["content"] = content
    if tool_calls is not None:
        delta["tool_calls"] = tool_calls
    choices = [] if usage else [{"index": 0, "delta": delta, "finish_reason": finish_reason}]
    return {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "test-model",
        "choices": choices,
        **({"usage": usage} if usage else {}),
    }


def streaming_groq(body: bytes | None = None, *, content=None):
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        headers = {"content-type": "text/event-stream"}
        if content is not None:
            return httpx2.Response(200, headers=headers, content=content)
        return httpx2.Response(200, headers=headers, content=body)

    provider = GroqProvider(
        {"id": "test-model", "supports_tools": True},
        api_key="test-key",
        base_url="https://llm.example.test/v1",
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return provider, sent


def test_the_adapter_streams_text_and_reads_the_usage():
    body = sse(
        chunk(content="Plants "),
        chunk(content="make food."),
        chunk(finish_reason="stop"),
        chunk(usage={"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16}),
    )
    provider, sent = streaming_groq(body)
    stream, pieces = collect()

    response = provider.chat_stream(MESSAGES, ChatOptions(), stream)

    assert pieces == ["Plants ", "make food."]
    assert response.text == "Plants make food."
    assert (response.tokens_in, response.tokens_out) == (12, 4)
    request = json.loads(sent[0].content)
    assert request["stream"] is True
    assert request["stream_options"] == {"include_usage": True}  # usage arrives at the end


def test_the_adapter_assembles_tool_calls_from_pieces():
    first = {
        "index": 0,
        "id": "call_1",
        "type": "function",
        "function": {"name": "list_tasks", "arguments": '{"sta'},
    }
    rest = {"index": 0, "function": {"arguments": 'tus": "todo"}'}}
    provider, _ = streaming_groq(
        sse(chunk(tool_calls=[first]), chunk(tool_calls=[rest], finish_reason="tool_calls"))
    )
    stream, pieces = collect()

    response = provider.chat_stream(MESSAGES, ChatOptions(tools=[{"type": "function"}]), stream)

    assert pieces == []  # asking for a tool shows no text
    assert response.tool_calls == [ToolCall("call_1", "list_tasks", '{"status": "todo"}')]


def test_the_adapter_stops_reading_when_asked():
    provider, _ = streaming_groq(
        sse(chunk(content="one "), chunk(content="two "), chunk(content="three"))
    )
    stream, pieces = collect()
    stream.should_stop = lambda: len(pieces) >= 1

    response = provider.chat_stream(MESSAGES, ChatOptions(), stream)

    assert response.text == "one " and response.stopped is True


def test_a_connection_lost_mid_stream_is_provider_unavailable():
    def broken_body():
        yield sse(chunk(content="one "), done=False)
        raise httpx2.ReadError("connection lost")

    provider, _ = streaming_groq(content=broken_body())
    stream, pieces = collect()

    with pytest.raises(ProviderUnavailableError):
        provider.chat_stream(MESSAGES, ChatOptions(), stream)
    assert pieces == ["one "]


def test_an_empty_streamed_answer_is_an_error():
    provider, _ = streaming_groq(sse(chunk(finish_reason="content_filter")))
    stream, _ = collect()

    with pytest.raises(Exception, match="empty answer"):
        provider.chat_stream(MESSAGES, ChatOptions(), stream)
