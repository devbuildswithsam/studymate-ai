"""The tasks table and its migration (guide 7.1). SMA-40, written test-first.

Checked at the database level (plain SQL), because tasks are written by the API now and
by the AI's MCP tools in SMA-41: the rules must hold whoever writes.
"""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db.session import make_engine


def sql(session, statement: str, **params):
    result = session.execute(text(statement), params)
    return result.all() if result.returns_rows else None


@pytest.fixture
def user_id(db_session) -> str:
    sql(
        db_session,
        "INSERT INTO users (id, email, created_at) VALUES ('u1', 'a@x.dev', '2026-11-17')",
    )
    db_session.commit()
    return "u1"


def insert_task(session, **columns):
    columns = {
        "id": "t1",
        "user_id": "u1",
        "title": "Revise ch. 3",
        "created_at": "2026-11-17",
        **columns,
    }
    names = ", ".join(columns)
    values = ", ".join(f":{name}" for name in columns)
    sql(session, f"INSERT INTO tasks ({names}) VALUES ({values})", **columns)


def test_the_tasks_table_exists_with_its_user_index(db_url):
    inspector = inspect(make_engine(db_url))

    columns = {c["name"] for c in inspector.get_columns("tasks")}
    assert columns == {
        "id",
        "user_id",
        "title",
        "description",
        "due_date",
        "priority",
        "status",
        "document_id",
        "created_by",
        "created_at",
        "completed_at",
    }
    assert "ix_tasks_user_id" in {i["name"] for i in inspector.get_indexes("tasks")}


def test_defaults_come_from_the_database(db_session, user_id):
    insert_task(db_session)  # only the required columns

    row = sql(db_session, "SELECT status, priority, created_by FROM tasks")[0]

    assert tuple(row) == ("todo", "medium", "user")


@pytest.mark.parametrize(
    "column, bad_value",
    [("status", "blocked"), ("priority", "urgent"), ("created_by", "robot")],
)
def test_the_database_refuses_values_outside_the_allowed_lists(
    db_session, user_id, column, bad_value
):
    with pytest.raises(IntegrityError, match="CHECK constraint failed"):
        insert_task(db_session, **{column: bad_value})


def test_a_task_needs_an_existing_user(db_session):
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        insert_task(db_session, user_id="nobody")


def test_deleting_a_user_deletes_their_tasks(db_session, user_id):
    insert_task(db_session)
    db_session.commit()

    sql(db_session, "DELETE FROM users WHERE id = 'u1'")
    db_session.commit()

    assert sql(db_session, "SELECT COUNT(*) FROM tasks")[0][0] == 0
