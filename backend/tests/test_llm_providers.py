"""Tests for the LLM providers: Gemini/Groq adapters (HTTP mocked) and the fake. SMA-21.

No real API is called: httpx2.MockTransport plays the provider's server.
"""

import json

import httpx2
import pytest

from app.services.llm.base import ChatOptions, LLMProvider
from app.services.llm.exceptions import (
    LLMConfigError,
    LLMError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.services.llm.fake import FakeProvider
from app.services.llm.gemini import GeminiProvider
from app.services.llm.groq import GroqProvider

MESSAGES = [{"role": "user", "content": "What is photosynthesis?"}]
MODEL_CONFIG = {"id": "test-model", "supports_tools": True, "supports_json": None}


def completion(content: str | None = "Plants make food from light.", finish_reason="stop"):
    """A minimal OpenAI-format chat completion, as a provider would send it."""
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
    }


def make_provider(provider_cls, respond):
    """Build an adapter whose 'server' is the respond(request) function. Returns (provider, sent)."""
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return respond(request)

    provider = provider_cls(
        MODEL_CONFIG,
        api_key="test-key",
        base_url="https://llm.example.test/v1",
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return provider, sent


ADAPTERS = [GeminiProvider, GroqProvider]


# --- Happy path -------------------------------------------------------------------


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_chat_returns_normalised_response(provider_cls):
    provider, _ = make_provider(provider_cls, lambda r: httpx2.Response(200, json=completion()))

    response = provider.chat(MESSAGES)

    assert response.text == "Plants make food from light."
    assert (response.tokens_in, response.tokens_out) == (12, 7)
    assert response.model == "test-model"
    assert response.provider == provider_cls.name
    assert response.latency_ms >= 0


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_chat_sends_model_messages_options_and_key(provider_cls):
    provider, sent = make_provider(provider_cls, lambda r: httpx2.Response(200, json=completion()))

    provider.chat(MESSAGES, ChatOptions(temperature=0.5, max_tokens=200, json_mode=True))

    request = sent[0]
    body = json.loads(request.content)
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    assert body["model"] == "test-model"
    assert body["messages"] == MESSAGES
    assert body["temperature"] == 0.5
    assert body["max_tokens"] == 200
    assert body["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_json_mode_off_sends_no_response_format(provider_cls):
    provider, sent = make_provider(provider_cls, lambda r: httpx2.Response(200, json=completion()))

    provider.chat(MESSAGES)

    assert "response_format" not in json.loads(sent[0].content)


# --- Errors become our types ------------------------------------------------------


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_429_with_retry_after_header_is_rate_limited(provider_cls):
    provider, _ = make_provider(
        provider_cls,
        lambda r: httpx2.Response(
            429, headers={"retry-after": "7"}, json={"error": {"message": "Rate limit reached"}}
        ),
    )

    with pytest.raises(RateLimitedError) as caught:
        provider.chat(MESSAGES)

    assert caught.value.retry_after == 7.0
    assert caught.value.provider == provider_cls.name
    assert "Rate limit reached" in str(caught.value)  # the provider's own message is kept


def test_gemini_429_reads_retry_delay_from_the_body():
    # Gemini quirk: the wait is in the body (google.rpc.RetryInfo), wrapped in a list.
    body = [
        {
            "error": {
                "code": 429,
                "message": "Quota exceeded",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "17s"}
                ],
            }
        }
    ]
    provider, _ = make_provider(GeminiProvider, lambda r: httpx2.Response(429, json=body))

    with pytest.raises(RateLimitedError) as caught:
        provider.chat(MESSAGES)

    assert caught.value.retry_after == 17.0
    assert "Quota exceeded" in str(caught.value)


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_429_without_a_wait_time_has_no_retry_after(provider_cls):
    provider, _ = make_provider(provider_cls, lambda r: httpx2.Response(429, json={}))

    with pytest.raises(RateLimitedError) as caught:
        provider.chat(MESSAGES)

    assert caught.value.retry_after is None


@pytest.mark.parametrize("provider_cls", ADAPTERS)
@pytest.mark.parametrize("status", [401, 403, 404])
def test_bad_key_or_model_is_a_config_error(provider_cls, status):
    provider, _ = make_provider(
        provider_cls, lambda r: httpx2.Response(status, json={"error": {"message": "nope"}})
    )

    with pytest.raises(LLMConfigError) as caught:
        provider.chat(MESSAGES)

    assert caught.value.status_code == status


# SMA-54: Gemini rejects a bad key with HTTP 400, not 401/403. This is the real body
# (captured by hand with a fake key, 2026-11-15): list-wrapped, generic INVALID_ARGUMENT.
GEMINI_BAD_KEY_BODY = [
    {
        "error": {
            "code": 400,
            "message": "Please pass a valid API key",
            "status": "INVALID_ARGUMENT",
        }
    }
]
# Google's native API names the problem explicitly; accept that form too.
GEMINI_KEY_INVALID_REASON_BODY = [
    {
        "error": {
            "code": 400,
            "message": "API key not valid.",
            "status": "INVALID_ARGUMENT",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}
            ],
        }
    }
]


@pytest.mark.parametrize("body", [GEMINI_BAD_KEY_BODY, GEMINI_KEY_INVALID_REASON_BODY])
def test_gemini_400_for_a_bad_key_is_a_config_error(body):
    provider, _ = make_provider(GeminiProvider, lambda r: httpx2.Response(400, json=body))

    with pytest.raises(LLMConfigError) as caught:
        provider.chat(MESSAGES)

    assert caught.value.status_code == 400
    assert "test-key" not in str(caught.value)  # the key itself is never in the message


def test_gemini_other_400s_stay_ordinary_errors():
    # A badly formed request is our bug, not a config problem: don't call it one.
    body = [
        {
            "error": {
                "code": 400,
                "message": "Invalid JSON payload received.",
                "status": "INVALID_ARGUMENT",
            }
        }
    ]
    provider, _ = make_provider(GeminiProvider, lambda r: httpx2.Response(400, json=body))

    with pytest.raises(LLMError) as caught:
        provider.chat(MESSAGES)

    assert not isinstance(caught.value, LLMConfigError)
    assert caught.value.status_code == 400


@pytest.mark.parametrize("provider_cls", ADAPTERS)
@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_is_provider_unavailable(provider_cls, status):
    provider, _ = make_provider(provider_cls, lambda r: httpx2.Response(status, text="overloaded"))

    with pytest.raises(ProviderUnavailableError) as caught:
        provider.chat(MESSAGES)

    assert caught.value.status_code == status


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_timeout_is_provider_timeout(provider_cls):
    def too_slow(request):
        raise httpx2.ReadTimeout("no answer", request=request)

    provider, _ = make_provider(provider_cls, too_slow)

    with pytest.raises(ProviderTimeoutError):
        provider.chat(MESSAGES)


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_connection_failure_is_provider_unavailable(provider_cls):
    def unreachable(request):
        raise httpx2.ConnectError("no route", request=request)

    provider, _ = make_provider(provider_cls, unreachable)

    with pytest.raises(ProviderUnavailableError):
        provider.chat(MESSAGES)


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_failures_are_not_retried_by_the_sdk(provider_cls):
    provider, sent = make_provider(provider_cls, lambda r: httpx2.Response(503, text="busy"))

    with pytest.raises(ProviderUnavailableError):
        provider.chat(MESSAGES)

    assert len(sent) == 1  # max_retries=0: retry/fallback is decided in SMA-22


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_empty_answer_is_an_error(provider_cls):
    provider, _ = make_provider(
        provider_cls,
        lambda r: httpx2.Response(
            200, json=completion(content=None, finish_reason="content_filter")
        ),
    )

    with pytest.raises(LLMError, match="content_filter"):
        provider.chat(MESSAGES)


# --- Capabilities -----------------------------------------------------------------


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_supports_reads_models_yaml_flags(provider_cls):
    provider, _ = make_provider(provider_cls, lambda r: httpx2.Response(200, json=completion()))

    assert provider.supports("tools") is True
    assert provider.supports("json") is False  # null in models.yaml = not tested = no


# --- The interface ----------------------------------------------------------------


def test_a_provider_without_chat_cannot_be_created():
    class Incomplete(LLMProvider):
        name = "incomplete"

    with pytest.raises(TypeError):
        Incomplete({"id": "x"})


# --- FakeProvider -----------------------------------------------------------------


def test_fake_is_an_llm_provider():
    assert isinstance(FakeProvider(), LLMProvider)


def test_fake_returns_replies_in_order_then_repeats_the_last():
    fake = FakeProvider(replies=["first", "second"])

    texts = [fake.chat(MESSAGES).text for _ in range(3)]

    assert texts == ["first", "second", "second"]


def test_fake_records_what_it_was_asked():
    fake = FakeProvider()

    response = fake.chat(MESSAGES)

    assert fake.calls == [MESSAGES]
    assert response.provider == "fake"
    assert response.tokens_in == 3  # "What is photosynthesis?" -> 3 words


def test_fake_raises_the_error_it_was_given():
    fake = FakeProvider(error=RateLimitedError("slow down", "fake", retry_after=1))

    with pytest.raises(RateLimitedError):
        fake.chat(MESSAGES)


def test_fake_capabilities_can_be_configured():
    fake = FakeProvider(model_config={"id": "fake-no-tools", "supports_tools": False})

    assert fake.supports("tools") is False
    assert fake.model == "fake-no-tools"


# --- Tools (SMA-42) -----------------------------------------------------------------

from app.services.llm.base import ToolCall  # noqa: E402

TOOLS = [{"type": "function", "function": {"name": "list_tasks", "parameters": {}}}]
GEMINI_EXTRA = {"google": {"thought_signature": "EpQDCpEDAWkU"}}


def tool_call_completion():
    """A reply that asks for a tool instead of answering (no text at all)."""
    body = completion(content=None, finish_reason="tool_calls")
    body["choices"][0]["message"]["tool_calls"] = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "list_tasks", "arguments": '{"status": "todo"}'},
            "extra_content": GEMINI_EXTRA,  # Gemini's thinking models add this (SMA-39)
        }
    ]
    return body


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_tools_are_sent_when_given_and_not_otherwise(provider_cls):
    provider, sent = make_provider(provider_cls, lambda r: httpx2.Response(200, json=completion()))

    provider.chat(MESSAGES)
    provider.chat(MESSAGES, ChatOptions(tools=TOOLS))

    assert "tools" not in json.loads(sent[0].content)
    assert json.loads(sent[1].content)["tools"] == TOOLS


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_a_reply_asking_for_tools_is_not_an_empty_answer(provider_cls):
    provider, _ = make_provider(
        provider_cls, lambda r: httpx2.Response(200, json=tool_call_completion())
    )

    response = provider.chat(MESSAGES, ChatOptions(tools=TOOLS))

    assert response.text == ""
    assert response.tool_calls == [
        ToolCall(
            id="call_1",
            name="list_tasks",
            arguments='{"status": "todo"}',
            extra={"extra_content": GEMINI_EXTRA},  # kept, to be sent back unchanged
        )
    ]


@pytest.mark.parametrize("provider_cls", ADAPTERS)
def test_a_plain_answer_has_no_tool_calls(provider_cls):
    provider, _ = make_provider(provider_cls, lambda r: httpx2.Response(200, json=completion()))

    assert provider.chat(MESSAGES, ChatOptions(tools=TOOLS)).tool_calls == []


def test_a_tool_call_goes_back_into_the_history_with_its_extras():
    call = ToolCall("call_1", "list_tasks", "{}", extra={"extra_content": GEMINI_EXTRA})

    assert call.as_message_part() == {
        "id": "call_1",
        "type": "function",
        "function": {"name": "list_tasks", "arguments": "{}"},
        "extra_content": GEMINI_EXTRA,
    }


def test_the_fake_provider_can_ask_for_tools():
    fake = FakeProvider(replies=[[ToolCall("c1", "list_tasks", "{}")], "Done."])

    first = fake.chat(MESSAGES, ChatOptions(tools=TOOLS))
    second = fake.chat(MESSAGES, ChatOptions(tools=TOOLS))

    assert (first.text, [c.name for c in first.tool_calls]) == ("", ["list_tasks"])
    assert (second.text, second.tool_calls) == ("Done.", [])
    assert fake.options[0].tools == TOOLS
