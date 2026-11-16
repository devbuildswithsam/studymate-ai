"""Shared pytest fixtures. SMA-20."""

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, Settings, get_settings
from app.db.session import make_engine
from app.main import app


def alembic_config(database_url: str) -> Config:
    config = Config(BACKEND_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def run_migrations(database_url: str) -> None:
    """`alembic upgrade head` against the given database (SMA-27), from Python."""
    command.upgrade(alembic_config(database_url), "head")


@pytest.fixture
def db_url(tmp_path) -> str:
    """A fresh temporary SQLite database, built by the real migrations (SMA-28)."""
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    run_migrations(url)
    return url


@pytest.fixture
def db_session(db_url):
    """A session on that database; closed after the test."""
    engine = make_engine(db_url)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


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
