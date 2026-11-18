"""The conversations repository, written test-first. SMA-30.

Every lookup takes user_id: another user's conversation behaves as if it doesn't exist.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError, InvalidRequestError

from app.models import LLMCall, Message, User
from app.repositories import conversations as repo
from app.services.llm.fallback import Attempt


@pytest.fixture
def alice(db_session) -> User:
    user = User(email="alice@example.com")
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def bob(db_session) -> User:
    user = User(email="bob@example.com")
    db_session.add(user)
    db_session.flush()
    return user


def add_messages(db, conversation, *contents: str) -> None:
    for n, content in enumerate(contents):
        repo.add_message(
            db, conversation, role="user" if n % 2 == 0 else "assistant", content=content
        )


# --- Create, list, get, rename, delete ---------------------------------------------


def test_create_then_get_my_conversation(db_session, alice):
    created = repo.create_conversation(db_session, alice.id, provider="groq", model="m1")

    found = repo.get_conversation(db_session, alice.id, created.id)

    assert found.id == created.id
    assert (found.user_id, found.provider, found.model, found.title) == (
        alice.id,
        "groq",
        "m1",
        None,
    )


def test_another_users_conversation_is_not_found(db_session, alice, bob):
    mine = repo.create_conversation(db_session, alice.id)

    assert repo.get_conversation(db_session, bob.id, mine.id) is None
    assert repo.rename_conversation(db_session, bob.id, mine.id, "hacked") is None
    assert repo.delete_conversation(db_session, bob.id, mine.id) is False
    assert repo.get_conversation(db_session, alice.id, mine.id).title is None  # untouched


def test_list_shows_only_my_conversations_most_recent_activity_first(db_session, alice, bob):
    older = repo.create_conversation(db_session, alice.id)
    newer = repo.create_conversation(db_session, alice.id)
    repo.create_conversation(db_session, bob.id)
    # Explicit times: Windows' clock is too coarse to tell rows made microseconds apart.
    older.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    newer.updated_at = datetime(2026, 1, 2, tzinfo=UTC)
    assert [c.id for c in repo.list_conversations(db_session, alice.id)] == [newer.id, older.id]

    add_messages(db_session, older, "a new message makes it the most recent")

    assert [c.id for c in repo.list_conversations(db_session, alice.id)] == [older.id, newer.id]


def test_rename(db_session, alice):
    conversation = repo.create_conversation(db_session, alice.id)

    renamed = repo.rename_conversation(db_session, alice.id, conversation.id, "Osmosis")

    assert renamed.title == "Osmosis"


def test_delete_removes_the_conversation_and_its_messages(db_session, alice):
    conversation = repo.create_conversation(db_session, alice.id)
    add_messages(db_session, conversation, "q", "a")

    assert repo.delete_conversation(db_session, alice.id, conversation.id) is True
    db_session.commit()

    assert repo.get_conversation(db_session, alice.id, conversation.id) is None
    assert db_session.scalar(select(func.count()).select_from(Message)) == 0


# --- Messages ----------------------------------------------------------------------


def test_messages_get_positions_1_2_3_in_order(db_session, alice):
    conversation = repo.create_conversation(db_session, alice.id)
    add_messages(db_session, conversation, "q1", "a1", "q2")

    found = repo.get_conversation(db_session, alice.id, conversation.id, with_messages=True)

    assert [(m.position, m.content) for m in found.messages] == [(1, "q1"), (2, "a1"), (3, "q2")]


def test_two_messages_can_never_share_a_position(db_session, alice):
    conversation = repo.create_conversation(db_session, alice.id)
    add_messages(db_session, conversation, "q1")
    db_session.add(Message(conversation_id=conversation.id, role="user", content="x", position=1))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_recent_messages_are_the_last_n_oldest_first(db_session, alice):
    conversation = repo.create_conversation(db_session, alice.id)
    add_messages(db_session, conversation, *[f"m{n}" for n in range(1, 8)])

    recent = repo.recent_messages(db_session, alice.id, conversation.id, limit=3)

    assert [m.content for m in recent] == ["m5", "m6", "m7"]


def test_recent_messages_of_another_users_conversation_are_empty(db_session, alice, bob):
    conversation = repo.create_conversation(db_session, alice.id)
    add_messages(db_session, conversation, "secret")

    assert repo.recent_messages(db_session, bob.id, conversation.id, limit=10) == []


def test_an_answer_keeps_its_details(db_session, alice):
    conversation = repo.create_conversation(db_session, alice.id)

    answer = repo.add_message(
        db_session,
        conversation,
        role="assistant",
        content="Osmosis is...",
        provider="gemini",
        model="m1",
        mode="general",
        fallback_used=True,
        tokens_in=12,
        tokens_out=34,
    )
    db_session.commit()

    saved = db_session.get(Message, answer.id)
    assert (saved.provider, saved.model, saved.mode) == ("gemini", "m1", "general")
    assert (saved.fallback_used, saved.tokens_in, saved.tokens_out) == (True, 12, 34)


# --- N+1: messages are never loaded by a hidden query ----------------------------
# Lazy loading runs one query per conversation the moment .messages is touched, so a
# loop over N conversations makes 1 + N queries. lazy="raise" turns that into an error.


def test_touching_messages_without_asking_for_them_is_an_error(db_session, alice):
    conversation = repo.create_conversation(db_session, alice.id)
    add_messages(db_session, conversation, "q")
    db_session.commit()
    db_session.expunge_all()  # forget everything: start from the database, like a new request

    found = repo.get_conversation(db_session, alice.id, conversation.id)  # no with_messages

    with pytest.raises(InvalidRequestError, match="lazy='raise'"):
        _ = found.messages  # just touching it must fail


def count_queries(db_session) -> list[str]:
    statements: list[str] = []
    event.listen(
        db_session.get_bind(),
        "before_cursor_execute",
        lambda conn, cursor, statement, *args: statements.append(statement),
    )
    return statements


@pytest.mark.parametrize("message_count", [2, 20])
def test_a_conversation_with_messages_loads_in_three_queries(db_session, alice, message_count):
    conversation = repo.create_conversation(db_session, alice.id)
    add_messages(db_session, conversation, *["x"] * message_count)
    db_session.commit()
    db_session.expunge_all()  # forget everything: start from the database, like a new request
    statements = count_queries(db_session)

    found = repo.get_conversation(db_session, alice.id, conversation.id, with_messages=True)
    contents = [m.content for m in found.messages]  # touching .messages must not query again
    actions = [a for m in found.messages for a in m.actions]  # nor .actions (SMA-43)

    assert len(contents) == message_count
    assert actions == []
    # The conversation, all its messages at once, all their actions at once: the same 3
    # for 2 or 20 messages (never one query per message: N+1).
    assert len(statements) == 3


# --- llm_calls ---------------------------------------------------------------------


def test_every_attempt_is_logged_as_an_llm_call(db_session, alice):
    conversation = repo.create_conversation(db_session, alice.id)
    attempts = [
        Attempt("m1", "gemini", "error", "rate_limited", latency_ms=120),
        Attempt(
            "m2",
            "groq",
            "ok",
            None,
            latency_ms=900,
            fallback_used=True,
            tokens_in=10,
            tokens_out=20,
        ),
    ]

    repo.log_llm_calls(db_session, alice.id, conversation.id, attempts, mode="general")
    db_session.commit()

    rows = db_session.scalars(select(LLMCall).order_by(LLMCall.latency_ms)).all()
    assert [
        (r.user_id, r.conversation_id, r.provider, r.model, r.status, r.error_type) for r in rows
    ] == [
        (alice.id, conversation.id, "gemini", "m1", "error", "rate_limited"),
        (alice.id, conversation.id, "groq", "m2", "ok", None),
    ]
    assert [(r.fallback_used, r.tokens_out, r.mode) for r in rows] == [
        (False, None, "general"),
        (True, 20, "general"),
    ]


def test_first_user_message(db_session, alice, bob):
    conversation = repo.create_conversation(db_session, alice.id)
    assert repo.first_user_message(db_session, alice.id, conversation.id) is None

    add_messages(db_session, conversation, "q1", "a1", "q2")

    assert repo.first_user_message(db_session, alice.id, conversation.id).content == "q1"
    assert repo.first_user_message(db_session, bob.id, conversation.id) is None
