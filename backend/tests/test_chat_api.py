"""Tests for POST /api/chat, written test-first. SMA-23.

The AI is always a FakeProvider: no real API is called.
"""

import pytest

from app.api.chat import SYSTEM_PROMPT
from app.api.deps import get_current_user_id
from app.main import app
from app.services.chat_history import ConversationStore, get_conversation_store
from app.services.llm.exceptions import ProviderUnavailableError, RateLimitedError
from app.services.llm.fake import FakeProvider
from app.services.llm.fallback import FallbackManager, get_fallback_manager
from app.services.llm.registry import ModelRegistry, get_registry

REGISTRY = ModelRegistry.model_validate(
    {
        "version": 1,
        "providers": {
            "gemini": {"base_url": "https://g.test/v1", "api_key_env": "GEMINI_API_KEY"},
            "groq": {"base_url": "https://q.test/v1", "api_key_env": "GROQ_API_KEY"},
        },
        "models": [
            {
                "id": "main",
                "provider": "gemini",
                "display_name": "Main",
                "priority": 1,
                "default_for": ["chat"],
            },
            {"id": "backup", "provider": "groq", "display_name": "Backup", "priority": 2},
        ],
    }
)


@pytest.fixture
def fakes():
    """One FakeProvider per model in REGISTRY. Tests can replace them before chatting."""
    return {
        "main": FakeProvider(replies=["answer from main"]),
        "backup": FakeProvider(replies=["answer from backup"]),
    }


@pytest.fixture
def chat_client(client, fakes):
    """The test client, with the AI replaced by FakeProviders."""
    manager = FallbackManager(REGISTRY, lambda m: fakes[m.id])
    store = ConversationStore()  # empty for every test: no shared conversations
    app.dependency_overrides[get_registry] = lambda: REGISTRY
    app.dependency_overrides[get_fallback_manager] = lambda: manager
    app.dependency_overrides[get_conversation_store] = lambda: store
    return client


def test_first_message_gets_a_labelled_reply_and_a_new_conversation(chat_client):
    response = chat_client.post("/api/chat", json={"message": "What is osmosis?"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "answer from main"
    assert body["provider"] == "fake"  # who actually answered
    assert body["model"] == "fake-model"
    assert body["mode"] == "general"
    assert body["fallback_used"] is False
    assert body["fallback_reason"] is None
    assert body["tokens_in"] > 0 and body["tokens_out"] > 0
    assert body["conversation_id"]  # a new id, so the next message can continue it


def test_three_turn_conversation_keeps_context(chat_client, fakes):
    fakes["main"].replies = ["Osmosis moves water.", "Through a membrane.", "Yes, in roots."]

    first = chat_client.post("/api/chat", json={"message": "What is osmosis?"}).json()
    conversation = {"conversation_id": first["conversation_id"]}
    second = chat_client.post("/api/chat", json={"message": "Through what?", **conversation})
    third = chat_client.post("/api/chat", json={"message": "Do plants use it?", **conversation})

    assert second.json()["conversation_id"] == first["conversation_id"]
    assert third.json()["reply"] == "Yes, in roots."
    # What the AI received on the 3rd call: the whole conversation so far, in order.
    assert fakes["main"].calls[2] == [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "What is osmosis?"},
        {"role": "assistant", "content": "Osmosis moves water."},
        {"role": "user", "content": "Through what?"},
        {"role": "assistant", "content": "Through a membrane."},
        {"role": "user", "content": "Do plants use it?"},
    ]


def test_only_the_last_10_history_messages_are_sent(chat_client, fakes):
    fakes["main"].replies = [f"answer {n}" for n in range(1, 8)]
    conversation_id = None
    for n in range(1, 8):  # 7 turns
        body = {"message": f"question {n}", "conversation_id": conversation_id}
        conversation_id = chat_client.post("/api/chat", json=body).json()["conversation_id"]

    sent = fakes["main"].calls[6]  # the 7th call
    assert sent[0]["role"] == "system"
    assert sent[1:-1] == [  # history: turns 2-6 only (10 messages); turn 1 was trimmed
        msg
        for n in range(2, 7)
        for msg in (
            {"role": "user", "content": f"question {n}"},
            {"role": "assistant", "content": f"answer {n}"},
        )
    ]
    assert sent[-1] == {"role": "user", "content": "question 7"}


# --- Limits ------------------------------------------------------------------------


def test_over_long_message_returns_422_in_our_error_format(chat_client, fakes):
    response = chat_client.post("/api/chat", json={"message": "x" * 4001})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "message" in error["message"]  # names the field that was wrong
    assert fakes["main"].calls == []  # rejected before any AI call


@pytest.mark.parametrize("message", ["", "   ", "\n\t"])
def test_empty_message_returns_422(chat_client, fakes, message):
    response = chat_client.post("/api/chat", json={"message": message})

    assert response.status_code == 422
    assert fakes["main"].calls == []


def test_a_message_of_exactly_4000_characters_is_accepted(chat_client):
    response = chat_client.post("/api/chat", json={"message": "x" * 4000})

    assert response.status_code == 200


def test_answers_are_capped_at_1024_tokens(chat_client, fakes):
    chat_client.post("/api/chat", json={"message": "Explain photosynthesis in detail."})

    assert fakes["main"].options[0].max_tokens == 1024


# --- Conversations belong to one user ----------------------------------------------


def test_unknown_conversation_returns_404(chat_client):
    response = chat_client.post("/api/chat", json={"message": "hi", "conversation_id": "nope"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_another_users_conversation_returns_404(chat_client):
    mine = chat_client.post("/api/chat", json={"message": "my notes"}).json()["conversation_id"]

    app.dependency_overrides[get_current_user_id] = lambda: "someone-else"
    response = chat_client.post("/api/chat", json={"message": "hi", "conversation_id": mine})

    assert response.status_code == 404  # same answer as "doesn't exist": reveals nothing


# --- Choosing a model --------------------------------------------------------------


def test_the_chosen_model_answers(chat_client, fakes):
    body = chat_client.post("/api/chat", json={"message": "hi", "model": "backup"}).json()

    assert body["reply"] == "answer from backup"
    assert fakes["main"].calls == []


def test_without_a_model_the_registry_chat_default_answers(chat_client, fakes):
    # Make "backup" (priority 2) the chat default: the default must win over priority.
    registry = REGISTRY.model_copy(deep=True)
    registry.models[0].default_for, registry.models[1].default_for = [], ["chat"]
    app.dependency_overrides[get_registry] = lambda: registry
    manager = FallbackManager(registry, lambda m: fakes[m.id])
    app.dependency_overrides[get_fallback_manager] = lambda: manager

    body = chat_client.post("/api/chat", json={"message": "hi"}).json()

    assert body["reply"] == "answer from backup"


def test_unknown_model_returns_400(chat_client):
    response = chat_client.post("/api/chat", json={"message": "hi", "model": "gpt-99"})

    assert response.status_code == 400
    assert "gpt-99" in response.json()["error"]["message"]


def test_provider_that_does_not_match_the_model_returns_400(chat_client):
    body = {"message": "hi", "model": "main", "provider": "groq"}  # main is a gemini model

    response = chat_client.post("/api/chat", json=body)

    assert response.status_code == 400


def test_matching_provider_is_accepted(chat_client):
    body = {"message": "hi", "model": "main", "provider": "gemini"}

    assert chat_client.post("/api/chat", json=body).status_code == 200


# --- Failures ----------------------------------------------------------------------


def test_rate_limited_main_falls_back_and_says_so(chat_client, fakes):
    fakes["main"] = FakeProvider(error=RateLimitedError("429", "gemini"))

    body = chat_client.post("/api/chat", json={"message": "hi"}).json()

    assert body["reply"] == "answer from backup"
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "main: rate-limited"


def test_all_models_failing_returns_503_and_saves_nothing(chat_client, fakes):
    first = chat_client.post("/api/chat", json={"message": "first question"}).json()
    # Change the existing fakes: the manager built them once and keeps reusing them.
    fakes["main"].error = ProviderUnavailableError("503", "gemini")
    fakes["backup"].error = ProviderUnavailableError("503", "groq")
    conversation = {"conversation_id": first["conversation_id"]}

    response = chat_client.post("/api/chat", json={"message": "lost question", **conversation})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "main: unavailable" in response.json()["error"]["message"]

    fakes["main"].error = None  # the AI recovers
    chat_client.post("/api/chat", json={"message": "next question", **conversation})
    sent = [m["content"] for m in fakes["main"].calls[-1]]
    assert "lost question" not in sent  # the failed turn was not saved
    assert "first question" in sent


# --- "Use fallback if the model fails" (SMA-26) -------------------------------------


def test_with_fallback_off_a_failing_model_returns_503_and_the_backup_is_not_used(
    chat_client, fakes
):
    fakes["main"].error = RateLimitedError("429", "gemini")

    response = chat_client.post("/api/chat", json={"message": "hi", "allow_fallback": False})

    assert response.status_code == 503
    assert "main: rate-limited" in response.json()["error"]["message"]
    assert fakes["backup"].calls == []


def test_fallback_is_on_by_default(chat_client, fakes):
    fakes["main"].error = RateLimitedError("429", "gemini")

    body = chat_client.post("/api/chat", json={"message": "hi"}).json()

    assert body["reply"] == "answer from backup"
    assert body["fallback_used"] is True
