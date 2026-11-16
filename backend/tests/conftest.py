"""Shared pytest fixtures. SMA-20."""

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.config import BACKEND_DIR, Settings, get_settings
from app.main import app


def run_migrations(database_url: str) -> None:
    """`alembic upgrade head` against the given database (SMA-27), from Python."""
    config = Config(BACKEND_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def settings_for_tests() -> Settings:
    # _env_file=None: ignore backend/.env so tests never see real keys or local tweaks.
    return Settings(_env_file=None, env="test", auth_mode="local")


@pytest.fixture
def client():
    # Dependency injection pays off: swap get_settings for the test version.
    app.dependency_overrides[get_settings] = settings_for_tests
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
