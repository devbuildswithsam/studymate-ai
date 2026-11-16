"""Conversations API and chat messages saved in the database, written test-first.

SMA-30 replaces POST /api/chat (SMA-23, in-memory) with /api/conversations/{id}/messages.
The chat tests from SMA-23/SMA-26 are ported here. The AI is always a FakeProvider.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.conversations import SYSTEM_PROMPT
from app.api.deps import get_current_user_id
from app.main import app
from app.models import LLMCall, Message, User
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


def use_fakes(fakes, registry=REGISTRY) -> None:
    manager = FallbackManager(registry, lambda m: fakes[m.id])
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_fallback_manager] = lambda: manager


@pytest.fixture
def chat_client(client, fakes):
    """The test client (seeded temporary database), with the AI replaced by FakeProviders."""
    use_fakes(fakes)
    return client


def new_conversation(client, **body) -> str:
    response = client.post("/api/conversations", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def send(client, message: str, conversation_id: str | None = None, **extra):
    """Send a chat message, starting a conversation first if none is given."""
    conversation_id = conversation_id or new_conversation(client)
    return client.post(
        f"/api/conversations/{conversation_id}/messages", json={"message": message, **extra}
    )


def count(db_session, model) -> int:
    return db_session.scalar(select(func.count()).select_from(model))


# --- Conversations CRUD ------------------------------------------------------------


def test_create_a_conversation(chat_client):
    response = chat_client.post("/api/conversations", json={})

    assert response.status_code == 201
    body = response.json()
    assert body["id"] and body["title"] is None
    assert body["created_at"] and body["updated_at"]


def test_create_with_a_model_saves_the_model_and_its_provider(chat_client):
    body = chat_client.post("/api/conversations", json={"model": "backup"}).json()

    assert (body["provider"], body["model"]) == ("groq", "backup")


def test_create_with_an_unknown_model_returns_400(chat_client):
    response = chat_client.post("/api/conversations", json={"model": "gpt-99"})

    assert response.status_code == 400


def test_list_my_conversations(chat_client):
    first = new_conversation(chat_client)
    second = new_conversation(chat_client)

    listed = chat_client.get("/api/conversations").json()

    assert {c["id"] for c in listed} == {first, second}


def test_get_a_conversation_with_its_messages_in_order(chat_client, fakes):
    fakes["main"].replies = ["Water moves.", "Through a membrane."]
    conversation_id = new_conversation(chat_client)
    send(chat_client, "What is osmosis?", conversation_id)
    send(chat_client, "Through what?", conversation_id)

    body = chat_client.get(f"/api/conversations/{conversation_id}").json()

    assert [(m["role"], m["content"]) for m in body["messages"]] == [
        ("user", "What is osmosis?"),
        ("assistant", "Water moves."),
        ("user", "Through what?"),
        ("assistant", "Through a membrane."),
    ]


def test_rename_a_conversation(chat_client):
    conversation_id = new_conversation(chat_client)

    response = chat_client.patch(
        f"/api/conversations/{conversation_id}", json={"title": "  Osmosis  "}
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Osmosis"  # surrounding spaces trimmed


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_rename_rejects_empty_or_too_long_titles(chat_client, title):
    conversation_id = new_conversation(chat_client)

    response = chat_client.patch(f"/api/conversations/{conversation_id}", json={"title": title})

    assert response.status_code == 422


def test_delete_a_conversation_and_its_messages(chat_client, db_session):
    conversation_id = new_conversation(chat_client)
    send(chat_client, "hi", conversation_id)

    response = chat_client.delete(f"/api/conversations/{conversation_id}")

    assert response.status_code == 204
    assert chat_client.get(f"/api/conversations/{conversation_id}").status_code == 404
    assert count(db_session, Message) == 0


# --- Another user's conversation looks like it doesn't exist ----------------------


@pytest.fixture
def bob(db_session) -> User:
    user = User(email="bob@example.com")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("GET", "", None),
        ("PATCH", "", {"title": "mine now"}),
        ("DELETE", "", None),
        ("POST", "/messages", {"message": "hi"}),
    ],
)
def test_another_users_conversation_returns_404(chat_client, bob, fakes, method, path, body):
    alices = new_conversation(chat_client)

    app.dependency_overrides[get_current_user_id] = lambda: bob.id
    response = chat_client.request(method, f"/api/conversations/{alices}{path}", json=body)

    assert response.status_code == 404  # same answer as "doesn't exist": reveals nothing
    assert fakes["main"].calls == []
    assert alices not in {c["id"] for c in chat_client.get("/api/conversations").json()}


def test_unknown_conversation_returns_404(chat_client, fakes):
    response = send(chat_client, "hi", conversation_id="nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert fakes["main"].calls == []


# --- Sending a message (ported from SMA-23) ----------------------------------------


def test_first_message_gets_a_labelled_reply(chat_client):
    conversation_id = new_conversation(chat_client)

    response = send(chat_client, "What is osmosis?", conversation_id)

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == conversation_id
    assert body["reply"] == "answer from main"
    assert body["provider"] == "fake"  # who actually answered
    assert body["model"] == "fake-model"
    assert body["mode"] == "general"
    assert body["fallback_used"] is False
    assert body["fallback_reason"] is None
    assert body["tokens_in"] > 0 and body["tokens_out"] > 0


def test_three_turn_conversation_keeps_context(chat_client, fakes):
    fakes["main"].replies = ["Osmosis moves water.", "Through a membrane.", "Yes, in roots."]
    conversation_id = new_conversation(chat_client)

    send(chat_client, "What is osmosis?", conversation_id)
    send(chat_client, "Through what?", conversation_id)
    third = send(chat_client, "Do plants use it?", conversation_id)

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
    conversation_id = new_conversation(chat_client)
    for n in range(1, 8):  # 7 turns
        send(chat_client, f"question {n}", conversation_id)

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


# --- Saved in the database (SMA-30) ------------------------------------------------


def test_both_messages_are_saved_with_the_answer_details(chat_client, fakes):
    fakes["main"] = FakeProvider(error=RateLimitedError("429", "gemini"))
    conversation_id = new_conversation(chat_client)
    send(chat_client, "What is osmosis?", conversation_id)

    question, answer = chat_client.get(f"/api/conversations/{conversation_id}").json()["messages"]

    assert (question["role"], question["provider"], question["model"]) == ("user", None, None)
    assert (answer["role"], answer["content"]) == ("assistant", "answer from backup")
    assert (answer["provider"], answer["model"], answer["mode"]) == (
        "fake",
        "fake-model",
        "general",
    )
    assert answer["fallback_used"] is True
    assert answer["tokens_in"] > 0 and answer["tokens_out"] > 0


def test_each_model_call_is_logged_to_llm_calls(chat_client, fakes, db_session):
    fakes["main"] = FakeProvider(error=RateLimitedError("429", "gemini"))
    conversation_id = new_conversation(chat_client)

    send(chat_client, "hi", conversation_id)

    calls = db_session.scalars(select(LLMCall)).all()
    assert sorted((c.model, c.status, c.error_type, c.fallback_used) for c in calls) == [
        ("backup", "ok", None, True),
        ("main", "error", "rate_limited", False),
    ]
    assert {c.conversation_id for c in calls} == {conversation_id}
    assert {c.mode for c in calls} == {"general"}


def test_history_survives_a_server_restart(client, db_session):
    first_fakes = {"main": FakeProvider(replies=["Osmosis moves water."])}
    use_fakes(first_fakes)
    conversation_id = new_conversation(client)
    send(client, "What is osmosis?", conversation_id)

    # "Restart": a new client and a brand-new FallbackManager. Nothing lives in memory,
    # only the database (the same file) is kept.
    after_restart = {"main": FakeProvider(replies=["In plant roots."])}
    use_fakes(after_restart)
    with TestClient(app, client=("127.0.0.1", 50000)) as restarted:
        history = restarted.get(f"/api/conversations/{conversation_id}").json()["messages"]
        reply = send(restarted, "Where does it happen?", conversation_id)

    assert [m["content"] for m in history] == ["What is osmosis?", "Osmosis moves water."]
    assert reply.status_code == 200
    assert after_restart["main"].calls[0][1:] == [  # the AI got the saved history
        {"role": "user", "content": "What is osmosis?"},
        {"role": "assistant", "content": "Osmosis moves water."},
        {"role": "user", "content": "Where does it happen?"},
    ]


# --- Limits (ported from SMA-23) ---------------------------------------------------


def test_over_long_message_returns_422_in_our_error_format(chat_client, fakes):
    response = send(chat_client, "x" * 4001)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "message" in error["message"]  # names the field that was wrong
    assert fakes["main"].calls == []  # rejected before any AI call


@pytest.mark.parametrize("message", ["", "   ", "\n\t"])
def test_empty_message_returns_422(chat_client, fakes, message):
    response = send(chat_client, message)

    assert response.status_code == 422
    assert fakes["main"].calls == []


def test_a_message_of_exactly_4000_characters_is_accepted(chat_client):
    assert send(chat_client, "x" * 4000).status_code == 200


def test_answers_are_capped_at_1024_tokens(chat_client, fakes):
    send(chat_client, "Explain photosynthesis in detail.")

    assert fakes["main"].options[0].max_tokens == 1024


# --- Choosing a model (ported from SMA-23/SMA-26) ----------------------------------


def test_the_chosen_model_answers(chat_client, fakes):
    body = send(chat_client, "hi", model="backup").json()

    assert body["reply"] == "answer from backup"
    assert fakes["main"].calls == []


def test_choosing_a_model_saves_it_on_the_conversation(chat_client, fakes):
    conversation_id = new_conversation(chat_client)
    send(chat_client, "hi", conversation_id, model="backup")

    conversation = chat_client.get(f"/api/conversations/{conversation_id}").json()
    send(chat_client, "again, no model given", conversation_id)

    assert (conversation["provider"], conversation["model"]) == ("groq", "backup")
    assert fakes["main"].calls == []  # the conversation's model answered again


def test_a_conversation_created_with_a_model_uses_it(chat_client, fakes):
    conversation_id = new_conversation(chat_client, model="backup")

    send(chat_client, "hi", conversation_id)

    assert fakes["main"].calls == []
    assert len(fakes["backup"].calls) == 1


def test_without_a_model_the_registry_chat_default_answers(chat_client, fakes):
    # Make "backup" (priority 2) the chat default: the default must win over priority.
    registry = REGISTRY.model_copy(deep=True)
    registry.models[0].default_for, registry.models[1].default_for = [], ["chat"]
    use_fakes(fakes, registry)

    body = send(chat_client, "hi").json()

    assert body["reply"] == "answer from backup"


def test_unknown_model_returns_400(chat_client):
    response = send(chat_client, "hi", model="gpt-99")

    assert response.status_code == 400
    assert "gpt-99" in response.json()["error"]["message"]


def test_provider_that_does_not_match_the_model_returns_400(chat_client):
    # main is a gemini model
    assert send(chat_client, "hi", model="main", provider="groq").status_code == 400


def test_matching_provider_is_accepted(chat_client):
    assert send(chat_client, "hi", model="main", provider="gemini").status_code == 200


# --- Failures (ported from SMA-23/SMA-26) ------------------------------------------


def test_rate_limited_main_falls_back_and_says_so(chat_client, fakes):
    fakes["main"] = FakeProvider(error=RateLimitedError("429", "gemini"))

    body = send(chat_client, "hi").json()

    assert body["reply"] == "answer from backup"
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "main: rate-limited"


def test_all_models_failing_returns_503_saves_no_message_but_logs_the_calls(
    chat_client, fakes, db_session
):
    conversation_id = new_conversation(chat_client)
    send(chat_client, "first question", conversation_id)
    # Change the existing fakes: the manager built them once and keeps reusing them.
    fakes["main"].error = ProviderUnavailableError("503", "gemini")
    fakes["backup"].error = ProviderUnavailableError("503", "groq")

    response = send(chat_client, "lost question", conversation_id)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "main: unavailable" in response.json()["error"]["message"]
    assert count(db_session, Message) == 2  # only the first turn: no half-saved turn
    failed = db_session.scalars(select(LLMCall).where(LLMCall.status == "error")).all()
    assert sorted(c.model for c in failed) == ["backup", "main"]  # but the calls are logged

    fakes["main"].error = None  # the AI recovers
    send(chat_client, "next question", conversation_id)
    sent = [m["content"] for m in fakes["main"].calls[-1]]
    assert "lost question" not in sent
    assert "first question" in sent


def test_with_fallback_off_a_failing_model_returns_503_and_the_backup_is_not_used(
    chat_client, fakes
):
    fakes["main"].error = RateLimitedError("429", "gemini")

    response = send(chat_client, "hi", allow_fallback=False)

    assert response.status_code == 503
    assert "main: rate-limited" in response.json()["error"]["message"]
    assert fakes["backup"].calls == []


def test_fallback_is_on_by_default(chat_client, fakes):
    fakes["main"].error = RateLimitedError("429", "gemini")

    body = send(chat_client, "hi").json()

    assert body["reply"] == "answer from backup"
    assert body["fallback_used"] is True


def test_the_old_in_memory_chat_endpoint_is_gone(chat_client):
    assert chat_client.post("/api/chat", json={"message": "hi"}).status_code == 404
