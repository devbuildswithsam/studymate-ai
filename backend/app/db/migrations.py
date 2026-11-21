"""Is the database at the newest migration? Checked when the app starts. SMA-61.

When a ticket adds a table, the code expects it at once, but your app.db only gets it
after `alembic upgrade head`. Without this check the app starts anyway and fails later,
on whichever page first touches the new table (SMA-61: Settings -> "no such table").
"""

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.config import BACKEND_DIR
from app.db.session import make_engine


class DatabaseBehind(RuntimeError):
    """The database isn't at the code's newest migration; the message says how to fix it."""


def check_database_is_current(database_url: str) -> None:
    newest = set(ScriptDirectory.from_config(Config(BACKEND_DIR / "alembic.ini")).get_heads())
    engine = make_engine(database_url)
    try:
        with engine.connect() as connection:
            # Read-only: the version Alembic wrote into the alembic_version table.
            current = set(MigrationContext.configure(connection).get_current_heads())
    finally:
        engine.dispose()
    if current != newest:
        at = ", ".join(sorted(current)) or "no migrations at all (empty)"
        raise DatabaseBehind(
            f"The database ({database_url}) is at {at}, but the code needs "
            f"{', '.join(sorted(newest))}. From backend/ with the venv active, run: "
            "alembic upgrade head"
        )
