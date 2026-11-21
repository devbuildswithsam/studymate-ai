"""The API refuses to start on a database that is behind the code's migrations. SMA-61.

Found in the SMA-61 browser check: the code had a new table (access_tokens) but app.db
was one migration behind, and the Settings page failed with a 500 ("no such table").
Now the mistake shows up at startup, with the command that fixes it. Test-first.
"""

import pytest
from alembic import command
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db.migrations import DatabaseBehind, check_database_is_current
from app.main import app
from tests.conftest import alembic_config

ONE_BEFORE_HEAD = "232c8b127f71"  # documents and chunks (SMA-44); head adds access_tokens


@pytest.fixture
def behind_db(tmp_path) -> str:
    url = f"sqlite:///{(tmp_path / 'behind.db').as_posix()}"
    command.upgrade(alembic_config(url), ONE_BEFORE_HEAD)
    return url


def test_a_database_at_the_latest_migration_passes(db_url):
    check_database_is_current(db_url)  # no error


def test_a_database_one_migration_behind_is_refused_with_the_fix(behind_db):
    with pytest.raises(DatabaseBehind) as caught:
        check_database_is_current(behind_db)

    message = str(caught.value)
    assert "alembic upgrade head" in message
    assert ONE_BEFORE_HEAD in message  # where it is...


def test_an_empty_database_is_refused(tmp_path):
    # E.g. a fresh clone where `alembic upgrade head` was skipped.
    with pytest.raises(DatabaseBehind, match="alembic upgrade head"):
        check_database_is_current(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")


def test_the_app_does_not_start_on_a_database_that_is_behind(behind_db):
    settings = Settings(_env_file=None, env="test", auth_mode="local", database_url=behind_db)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with pytest.raises(DatabaseBehind):
            with TestClient(app):  # entering runs the app's startup (lifespan)
                pass
    finally:
        app.dependency_overrides.clear()
