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
