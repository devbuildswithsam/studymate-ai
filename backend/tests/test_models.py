"""Tests for the database models and their first migration. SMA-28.

Every test runs on a temporary SQLite file built by the real Alembic migration
(the db_url / db_session fixtures), so these tests check the migration as well.
"""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.db.session import make_engine
from app.models import Conversation, LLMCall, Message, Note, User
from tests.conftest import alembic_config

APP_TABLES = {"users", "conversations", "messages", "notes", "llm_calls"}


def make_user(session, email="student@example.com") -> User:
    user = User(email=email, name="Student")
    session.add(user)
    session.flush()  # send the INSERT now (still inside the transaction) to get defaults
    return user


def count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


# --- The migration --------------------------------------------------------------------


def test_migration_creates_the_tables_and_indexes(db_url):
    inspector = inspect(make_engine(db_url))

    assert APP_TABLES <= set(inspector.get_table_names())
    indexed = {
        (table, column)
        for table in APP_TABLES
        for index in inspector.get_indexes(table)
        for column in index["column_names"]
    }
    assert {
        ("conversations", "user_id"),
        ("messages", "conversation_id"),
        ("notes", "user_id"),
        ("llm_calls", "user_id"),
        ("llm_calls", "conversation_id"),
    } <= indexed


def test_migration_downgrades_cleanly_and_upgrades_again(db_url):
    config = alembic_config(db_url)

    command.downgrade(config, "base")
    assert set(inspect(make_engine(db_url)).get_table_names()) <= {"alembic_version"}

    command.upgrade(config, "head")
    assert APP_TABLES <= set(inspect(make_engine(db_url)).get_table_names())


def test_the_migration_matches_the_models(db_url):
    # Alembic compares the migrated database with the models: any difference means
    # someone changed a model without writing a migration (or the other way round).
    with make_engine(db_url).connect() as conn:
        differences = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert differences == []


# --- Relationships --------------------------------------------------------------------


def test_a_conversation_has_messages_in_order_and_belongs_to_a_user(db_session):
    user = make_user(db_session)
    chat = Conversation(user=user, title="Osmosis", provider="gemini", model="gemini-3.5-flash")
    chat.messages.append(Message(role="user", content="What is osmosis?"))
    chat.messages.append(
        Message(
            role="assistant",
            content="Water moving through a membrane.",
            provider="groq",
            model="openai/gpt-oss-120b",
            mode="general",
            fallback_used=True,
            tokens_in=12,
            tokens_out=7,
            citations=[{"document": "bio.pdf", "page": 3}],
            tool_calls=None,
        )
    )
    db_session.add(chat)
    db_session.commit()
    db_session.expunge_all()  # forget the Python objects: read back from the database

    loaded = db_session.get(Conversation, chat.id)
    assert [m.role for m in loaded.messages] == ["user", "assistant"]
    answer = loaded.messages[1]
    assert answer.fallback_used is True
    assert answer.citations == [{"document": "bio.pdf", "page": 3}]  # JSON round trip
    assert answer.conversation.user.email == "student@example.com"
    assert loaded.created_at is not None and loaded.updated_at is not None
    assert isinstance(chat.id, str) and len(chat.id) == 36  # a UUID, not 1, 2, 3...


def test_a_note_can_point_to_the_message_it_was_saved_from(db_session):
    user = make_user(db_session)
    message = Message(role="assistant", content="Mitochondria make ATP.")
    db_session.add(Conversation(user=user, messages=[message]))
    note = Note(user=user, title="ATP", content="Mitochondria make ATP.", source_message=message)
    db_session.add(note)
    db_session.commit()

    assert note.source_message_id == message.id
    assert note.tags == []  # default
    assert user.notes == [note]


# --- What the database itself enforces (not just Python) ------------------------------


def test_deleting_a_user_deletes_everything_they_own(db_session):
    user = make_user(db_session)
    conversation = Conversation(user=user, messages=[Message(role="user", content="Hi")])
    db_session.add_all(
        [
            conversation,
            Note(user=user, title="n", content="c"),
            LLMCall(
                user=user,
                conversation=conversation,
                provider="gemini",
                model="m",
                mode="general",
                status="ok",
            ),
        ]
    )
    db_session.commit()

    # Plain SQL, so only the database's ON DELETE CASCADE can clean up, not the ORM.
    db_session.execute(text("DELETE FROM users"))
    db_session.commit()

    for model in (Conversation, Message, Note, LLMCall):
        assert count(db_session, model) == 0, model.__tablename__


def test_deleting_a_message_keeps_the_note_saved_from_it(db_session):
    user = make_user(db_session)
    message = Message(role="assistant", content="Keep me in a note.")
    db_session.add(Conversation(user=user, messages=[message]))
    note = Note(user=user, title="t", content="Keep me in a note.", source_message=message)
    db_session.add(note)
    db_session.commit()

    db_session.execute(text("DELETE FROM messages"))
    db_session.commit()
    db_session.refresh(note)

    assert note.source_message_id is None  # ON DELETE SET NULL: the note survives


def test_deleting_a_conversation_keeps_its_llm_call_records(db_session):
    user = make_user(db_session)
    conversation = Conversation(user=user)
    call = LLMCall(
        user=user,
        conversation=conversation,
        provider="groq",
        model="m",
        mode="general",
        status="error",
        error_type="rate_limited",
        latency_ms=850,
        fallback_used=False,
    )
    db_session.add_all([conversation, call])
    db_session.commit()

    db_session.execute(text("DELETE FROM conversations"))
    db_session.commit()
    db_session.refresh(call)

    assert call.conversation_id is None  # usage stats stay, the link goes
    assert call.error_type == "rate_limited"


def test_email_must_be_unique(db_session):
    make_user(db_session, "same@example.com")

    with pytest.raises(IntegrityError, match="UNIQUE"):
        make_user(db_session, "same@example.com")


@pytest.mark.parametrize(
    "bad_row",
    [
        "INSERT INTO messages (id, conversation_id, role, content, fallback_used, created_at) "
        "VALUES ('m1', :conversation_id, 'robot', 'x', 0, CURRENT_TIMESTAMP)",
        "INSERT INTO messages (id, conversation_id, role, content, mode, fallback_used, created_at) "
        "VALUES ('m2', :conversation_id, 'assistant', 'x', 'magic', 0, CURRENT_TIMESTAMP)",
        "INSERT INTO llm_calls (id, user_id, provider, model, mode, status, fallback_used, "
        "created_at) VALUES ('c1', :user_id, 'p', 'm', 'general', 'maybe', 0, CURRENT_TIMESTAMP)",
    ],
    ids=["unknown role", "unknown message mode", "unknown call status"],
)
def test_the_database_rejects_values_outside_the_allowed_lists(db_session, bad_row):
    user = make_user(db_session)
    conversation = Conversation(user=user)
    db_session.add(conversation)
    db_session.commit()

    with pytest.raises(IntegrityError, match="CHECK"):
        db_session.execute(text(bad_row), {"conversation_id": conversation.id, "user_id": user.id})
