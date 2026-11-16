"""Engine and sessions. SMA-27.

- Engine: knows how to connect to the database (one per database URL, reused).
- Session: one "unit of work". Changes stay in a transaction until commit();
  if anything fails, rollback() throws them all away, so the file never holds
  half-done work.
"""

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings


def make_engine(database_url: str) -> Engine:
    connect_args = {}
    if database_url.startswith("sqlite"):
        # FastAPI may run a request in a different thread than the one that opened
        # the connection; SQLite refuses that by default. Each session is still used
        # by one request at a time, so this is safe.
        connect_args["check_same_thread"] = False
    engine = create_engine(database_url, connect_args=connect_args)

    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    # SQLite ignores FOREIGN KEY constraints unless each connection turns them on.
    # Without this, deleting a conversation could leave orphan messages behind.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@lru_cache
def _session_factory(database_url: str) -> sessionmaker[Session]:
    # Cached per URL: building an engine (and its connection pool) per request would be slow.
    # expire_on_commit=False: objects stay readable after commit (e.g. to return them).
    return sessionmaker(make_engine(database_url), expire_on_commit=False)


def get_db(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed afterwards.

    Routes call session.commit() when their work is done. If the route raises
    first, close() rolls back whatever wasn't committed, so nothing half-written
    is saved (tested: no explicit rollback() is needed).
    """
    session = _session_factory(settings.database_url)()
    try:
        yield session
    finally:
        session.close()
