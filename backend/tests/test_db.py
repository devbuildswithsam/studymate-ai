"""Tests for the database foundation: engine, sessions, Alembic. SMA-27.

Every test uses its own temporary SQLite file (pytest's tmp_path), never app.db.
"""

import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table, inspect, text
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db.session import get_db, make_engine
from tests.conftest import run_migrations


def sqlite_url(tmp_path, name="test.db") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def test_default_database_url_is_a_local_sqlite_file():
    assert Settings(_env_file=None).database_url == "sqlite:///./app.db"


# --- Foreign keys: SQLite ignores them unless every connection switches them on ----


def test_foreign_keys_are_enforced(tmp_path):
    engine = make_engine(sqlite_url(tmp_path))
    metadata = MetaData()
    parent = Table("parent", metadata, Column("id", Integer, primary_key=True))
    child = Table(
        "child",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("parent_id", Integer, ForeignKey("parent.id"), nullable=False),
    )
    metadata.create_all(engine)  # fine for a throwaway test table; the app uses Alembic

    with engine.begin() as conn:
        conn.execute(parent.insert().values(id=1))
        conn.execute(child.insert().values(id=1, parent_id=1))  # real parent: OK

    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        with engine.begin() as conn:
            conn.execute(child.insert().values(id=2, parent_id=999))  # no such parent


# --- Alembic ------------------------------------------------------------------------


def test_alembic_upgrade_head_creates_an_empty_database(tmp_path):
    db_file = tmp_path / "fresh.db"
    assert not db_file.exists()

    run_migrations(sqlite_url(tmp_path, "fresh.db"))

    assert db_file.exists()
    app_tables = set(inspect(make_engine(sqlite_url(tmp_path, "fresh.db"))).get_table_names())
    app_tables.discard("alembic_version")  # Alembic's own bookkeeping table
    assert app_tables == set()  # no models yet: those arrive in SMA-28


# --- get_db: one session per request; commit keeps, error rolls back, always closed -


@pytest.fixture
def notes_db(tmp_path):
    """Settings pointing at a temp database with one small table to write to."""
    url = sqlite_url(tmp_path)
    with make_engine(url).begin() as conn:
        conn.execute(text("CREATE TABLE note (body TEXT NOT NULL)"))
    return Settings(_env_file=None, database_url=url)


def count_notes(settings: Settings) -> int:
    with make_engine(settings.database_url).connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM note")).scalar_one()


def test_get_db_commit_is_saved_and_the_session_is_closed(notes_db):
    requests = get_db(notes_db)
    session = next(requests)  # what FastAPI does before calling the route

    session.execute(text("INSERT INTO note (body) VALUES ('osmosis')"))
    session.commit()
    requests.close()  # what FastAPI does after the response

    assert count_notes(notes_db) == 1
    assert not session.in_transaction()  # closed: nothing left open


def test_get_db_rolls_back_when_the_request_fails(notes_db):
    requests = get_db(notes_db)
    session = next(requests)
    session.execute(text("INSERT INTO note (body) VALUES ('half-written')"))

    with pytest.raises(RuntimeError):
        requests.throw(RuntimeError("route crashed before commit"))

    assert count_notes(notes_db) == 0  # the half-done work never reached the file
    assert not session.in_transaction()
