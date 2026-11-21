"""Migrations must never lose data, in either direction. SMA-33, written test-first.

SQLite can't change most columns in place, so Alembic's batch mode rebuilds the table:
copy it, DROP the old one, rename the copy. With foreign keys enforced, that DROP runs the
ON DELETE rules: CASCADE would delete every child row, SET NULL would cut every link.
"""

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from tests.conftest import alembic_config, run_migrations


def sql(url: str, statement: str, **params):
    """Run one statement on a plain connection (foreign keys on, like the app)."""
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        result = connection.execute(text(statement), params)
        rows = result.all() if result.returns_rows else None
    engine.dispose()
    return rows


def seed_real_looking_data(url: str) -> None:
    """A user with a chat, its messages, a note saved from an answer, and a call log."""
    sql(url, "INSERT INTO users (id, email, created_at) VALUES ('u1', 'me@x.dev', '2026-11-01')")
    sql(
        url,
        "INSERT INTO conversations (id, user_id, title, created_at, updated_at) "
        "VALUES ('c1', 'u1', 'Osmosis', '2026-11-01', '2026-11-01')",
    )
    for position, (mid, role) in enumerate([("m1", "user"), ("m2", "assistant")], start=1):
        sql(
            url,
            "INSERT INTO messages (id, conversation_id, position, role, content, fallback_used, "
            "created_at) VALUES (:id, 'c1', :position, :role, 'text', 0, '2026-11-01')",
            id=mid,
            position=position,
            role=role,
        )
    sql(
        url,
        "INSERT INTO notes (id, user_id, title, content, source_message_id, tags, created_at, "
        "updated_at) VALUES ('n1', 'u1', 'Saved', 'text', 'm2', '[]', '2026-11-01', '2026-11-01')",
    )
    sql(
        url,
        "INSERT INTO llm_calls (id, user_id, conversation_id, provider, model, mode, status, "
        "fallback_used, created_at) VALUES ('l1', 'u1', 'c1', 'p', 'm', 'general', 'ok', 0, "
        "'2026-11-01')",
    )


def snapshot(url: str) -> dict:
    """Everything that must survive: the rows and the links between them."""
    return {
        "users": sql(url, "SELECT id FROM users"),
        "conversations": sql(url, "SELECT id, user_id, title FROM conversations"),
        "messages": sql(url, "SELECT id, conversation_id, role FROM messages ORDER BY id"),
        "note links": sql(url, "SELECT id, source_message_id FROM notes"),
        "call links": sql(url, "SELECT id, conversation_id FROM llm_calls"),
    }


def revisions_after_the_first() -> list[str]:
    """Every revision that has a previous one to step back to."""
    script = ScriptDirectory.from_config(alembic_config("sqlite://"))
    return [r.revision for r in script.walk_revisions() if r.down_revision is not None]


@pytest.mark.parametrize("revision", revisions_after_the_first())
def test_stepping_back_over_a_migration_and_forward_again_keeps_all_data(tmp_path, revision):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    config = alembic_config(url)
    command.upgrade(config, revision)
    seed_real_looking_data(url)
    before = snapshot(url)

    command.downgrade(config, "-1")
    assert snapshot(url) == before, "the downgrade lost data"
    command.upgrade(config, revision)
    assert snapshot(url) == before, "the upgrade lost data"
    assert sql(url, "PRAGMA foreign_key_check") == []  # no broken links left behind


def test_migrations_leave_foreign_keys_switched_on(tmp_path):
    # Migrations switch them off on their own connection; the app's connections still
    # switch them on (SMA-27's engine event).
    url = f"sqlite:///{(tmp_path / 'fk.db').as_posix()}"
    run_migrations(url)
    seed_real_looking_data(url)

    with pytest.raises(Exception, match="FOREIGN KEY"):
        sql(
            url,
            "INSERT INTO conversations (id, user_id, created_at, updated_at) "
            "VALUES ('orphan', 'nobody', '2026-11-01', '2026-11-01')",
        )


# --- SMA-33: conversations.mode ----------------------------------------------------

MODE_REVISION_PARENT = "823d220c6b31"  # the revision before conversations.mode


def columns(url: str, table: str) -> list[str]:
    return [row[1] for row in sql(url, f"PRAGMA table_info({table})")]


def test_existing_conversations_become_general_and_the_column_goes_away_on_downgrade(tmp_path):
    url = f"sqlite:///{(tmp_path / 'mode.db').as_posix()}"
    config = alembic_config(url)
    command.upgrade(config, MODE_REVISION_PARENT)
    seed_real_looking_data(url)

    command.upgrade(config, "head")
    assert sql(url, "SELECT id, mode FROM conversations") == [("c1", "general")]

    command.downgrade(config, MODE_REVISION_PARENT)
    assert "mode" not in columns(url, "conversations")
    assert sql(url, "SELECT id, title FROM conversations") == [("c1", "Osmosis")]


def test_the_database_only_accepts_general_or_study(tmp_path):
    url = f"sqlite:///{(tmp_path / 'check.db').as_posix()}"
    run_migrations(url)
    seed_real_looking_data(url)

    sql(url, "UPDATE conversations SET mode = 'study' WHERE id = 'c1'")  # allowed
    with pytest.raises(Exception, match="CHECK constraint failed"):
        sql(url, "UPDATE conversations SET mode = 'magic' WHERE id = 'c1'")


def test_a_new_conversation_row_defaults_to_general_even_without_the_orm(tmp_path):
    # server_default: the DATABASE fills it in, so plain SQL inserts (and old code) work too.
    url = f"sqlite:///{(tmp_path / 'default.db').as_posix()}"
    run_migrations(url)
    seed_real_looking_data(url)

    assert sql(url, "SELECT mode FROM conversations WHERE id = 'c1'") == [("general",)]


def test_existing_messages_are_numbered_in_order_when_position_is_added(tmp_path):
    # SMA-30's migration, fixed in SMA-33: it now works on a table that already has rows.
    url = f"sqlite:///{(tmp_path / 'pos.db').as_posix()}"
    config = alembic_config(url)
    command.upgrade(config, MODE_REVISION_PARENT)
    seed_real_looking_data(url)
    command.downgrade(config, "-1")  # back to before messages.position

    command.upgrade(config, MODE_REVISION_PARENT)

    assert sql(url, "SELECT id, position FROM messages ORDER BY position") == [("m1", 1), ("m2", 2)]


DOCUMENTS_REVISION = "232c8b127f71"  # SMA-44: documents, chunks; tasks.document_id gets its FK


def test_existing_tasks_survive_getting_a_document_foreign_key(tmp_path):
    # Adding the foreign key rebuilds the tasks table (SQLite batch mode): no row may be lost.
    url = f"sqlite:///{(tmp_path / 'docs.db').as_posix()}"
    config = alembic_config(url)
    command.upgrade(config, f"{DOCUMENTS_REVISION}-1")
    seed_real_looking_data(url)
    sql(
        url,
        "INSERT INTO tasks (id, user_id, title, document_id, created_at) VALUES "
        "('t1', 'u1', 'Revise', NULL, '2026-11-01'), "
        "('t2', 'u1', 'Old link', 'no-such-document', '2026-11-01')",
    )

    command.upgrade(config, DOCUMENTS_REVISION)

    # Both tasks kept; the link that pointed nowhere is cleared, so the FK holds.
    assert sql(url, "SELECT id, title, document_id FROM tasks ORDER BY id") == [
        ("t1", "Revise", None),
        ("t2", "Old link", None),
    ]
    assert sql(url, "PRAGMA foreign_key_check") == []
    command.downgrade(config, "-1")
    assert sql(url, "SELECT id FROM tasks ORDER BY id") == [("t1",), ("t2",)]


DOCX_REVISION = "15dc82b50fad"  # SMA-66: documents may be DOCX
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def a_document_with_a_chunk(url: str, doc_id: str, mime_type: str) -> None:
    sql(
        url,
        "INSERT INTO documents (id, user_id, filename, mime_type, size_bytes, status, created_at) "
        "VALUES (:id, 'u1', 'f', :mime, 1, 'ready', '2026-11-01')",
        id=doc_id,
        mime=mime_type,
    )
    sql(
        url,
        "INSERT INTO chunks (id, document_id, chunk_index, page, text, token_count) "
        "VALUES (:id, :doc, 0, 1, 'text', 1)",
        id=f"chunk-{doc_id}",
        doc=doc_id,
    )


def test_accepting_docx_keeps_every_document_and_its_chunks(tmp_path):
    url = f"sqlite:///{(tmp_path / 'docx.db').as_posix()}"
    config = alembic_config(url)
    command.upgrade(config, f"{DOCX_REVISION}-1")
    seed_real_looking_data(url)
    a_document_with_a_chunk(url, "d1", "application/pdf")

    command.upgrade(config, DOCX_REVISION)  # rebuilds the documents table

    assert sql(url, "SELECT id FROM chunks") == [("chunk-d1",)]  # no cascade during the rebuild
    # Long enough for the 71-character DOCX type (SQLite ignores lengths; Postgres wouldn't).
    column = "SELECT type FROM pragma_table_info('documents') WHERE name = 'mime_type'"
    assert sql(url, column) == [("VARCHAR(100)",)]
    a_document_with_a_chunk(url, "d2", DOCX)  # the new rule accepts DOCX
    with pytest.raises(Exception, match="CHECK constraint"):
        a_document_with_a_chunk(url, "d3", "image/png")  # and still nothing else


def test_downgrading_refuses_while_docx_documents_exist(tmp_path):
    url = f"sqlite:///{(tmp_path / 'docx.db').as_posix()}"
    config = alembic_config(url)
    command.upgrade(config, DOCX_REVISION)
    seed_real_looking_data(url)
    a_document_with_a_chunk(url, "d1", "application/pdf")
    a_document_with_a_chunk(url, "d2", DOCX)

    with pytest.raises(RuntimeError, match="Delete them in the app first"):
        command.downgrade(config, "-1")

    assert sql(url, "SELECT id FROM documents ORDER BY id") == [("d1",), ("d2",)]  # untouched
    sql(url, "DELETE FROM documents WHERE id = 'd2'")
    command.downgrade(config, "-1")  # without DOCX documents it works
    assert sql(url, "SELECT id FROM chunks") == [("chunk-d1",)]
