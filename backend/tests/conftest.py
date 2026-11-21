"""Shared pytest fixtures. SMA-20."""

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, Settings, get_settings
from app.db.seed import ensure_local_user
from app.db.session import make_engine
from app.main import app
from app.services.auth import LoginLimiter, get_login_limiter
from app.services.llm.embeddings import get_embedder
from app.services.llm.fake import FakeEmbeddingProvider, FakeProvider
from app.services.llm.fallback import FallbackManager, get_fallback_manager
from app.services.llm.registry import get_registry
from tests.auth_helpers import act_like_our_frontend, jwt_settings
from tests.tool_helpers import REGISTRY as TOOL_REGISTRY


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


def settings_for_tests(database_url: str) -> Settings:
    # _env_file=None: ignore backend/.env so tests never see real keys or local tweaks.
    return Settings(_env_file=None, env="test", auth_mode="local", database_url=database_url)


@pytest.fixture
def client(db_url, db_session):
    """The app on a temporary database that already holds the seeded local user (SMA-29)."""
    ensure_local_user(db_session)
    settings = settings_for_tests(db_url)
    # Dependency injection pays off: swap get_settings for the test version.
    app.dependency_overrides[get_settings] = lambda: settings
    # SMA-47: uploads embed their chunks. Every test gets a fake embedder, so no test can
    # ever reach the real API (CLAUDE.md); a test may swap in a failing fake.
    app.dependency_overrides[get_embedder] = lambda: (lambda: FakeEmbeddingProvider())
    # SMA-50: uploads also ask the chat AI for a summary. Same rule: a fake by default (it
    # answers with a valid summary); tests that need other answers override it.
    summary = '{"summary": "A test summary.", "key_points": ["A test key point."]}'
    default_ai = FallbackManager(get_registry(), lambda m: FakeProvider(replies=[summary]))
    app.dependency_overrides[get_fallback_manager] = lambda: default_ai
    # client=127.0.0.1: requests come from this computer, like the browser via Vite.
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        yield c
    app.dependency_overrides.clear()


# --- Real accounts (SMA-57, SMA-58) ------------------------------------------------


@pytest.fixture
def jwt_api(db_url):
    """The app in AUTH_MODE=jwt on a temporary database, acting like our frontend:

    - over https, because the session cookie is Secure (browsers make an exception for
      localhost; the test client doesn't);
    - on every POST/PUT/PATCH/DELETE it copies the CSRF cookie into the X-CSRF-Token
      header, as frontend/src/api/client.ts does. Set `.auto_csrf = False` to act like
      another website, which can't read our cookies.
    """
    settings = jwt_settings(db_url)
    limiter = LoginLimiter()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_login_limiter] = lambda: limiter
    with TestClient(app, base_url="https://testserver", client=("127.0.0.1", 50000)) as c:
        act_like_our_frontend(c)
        yield c
    app.dependency_overrides.clear()


# --- Chat with MCP tools (SMA-42, SMA-43) ------------------------------------------


@pytest.fixture
def tool_fakes():
    """The fake AIs behind TOOL_REGISTRY's two models: set .replies in a test."""
    return {
        "tools-model": FakeProvider(replies=["plain answer"]),
        "plain-model": FakeProvider(replies=["answer without tools"]),
    }


@pytest.fixture
def tool_chat(client, tool_fakes):
    """send(message) in a new chat, answered by tool_fakes: (conversation_id, response)."""
    manager = FallbackManager(TOOL_REGISTRY, lambda m: tool_fakes[m.id])
    app.dependency_overrides[get_registry] = lambda: TOOL_REGISTRY
    app.dependency_overrides[get_fallback_manager] = lambda: manager

    def send(message: str, **extra):
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        response = client.post(
            f"/api/conversations/{conversation_id}/messages", json={"message": message, **extra}
        )
        return conversation_id, response

    return send
