"""Single-user local auth mode and its guards, written test-first. SMA-29 (guide 7.1a)."""

import os
import subprocess
import sys

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from starlette.requests import Request

from app.api.deps import get_current_user
from app.config import BACKEND_DIR, Settings
from app.db.seed import LOCAL_USER_EMAIL, ensure_local_user
from app.main import app
from app.models import User

GUARD_MESSAGE = "AUTH_MODE=local is not allowed when ENV=production"


def count_users(session) -> int:
    return session.scalar(select(func.count()).select_from(User))


def request_from(host: str | None) -> Request:
    """A bare request object, as if it came from this client address."""
    client = (host, 50000) if host else None
    return Request({"type": "http", "client": client, "headers": []})


# --- Startup guard: production + local mode is refused ------------------------------


def test_settings_refuse_local_auth_in_production():
    with pytest.raises(ValidationError, match=GUARD_MESSAGE):
        Settings(_env_file=None, env="production", auth_mode="local")


@pytest.mark.parametrize("env", ["development", "test"])
def test_settings_allow_local_auth_outside_production(env):
    assert Settings(_env_file=None, env=env, auth_mode="local").auth_mode == "local"


def test_the_guard_error_does_not_print_api_keys():
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, env="production", gemini_api_key="FAKE-SECRET-123")

    assert GUARD_MESSAGE in str(caught.value)
    assert "FAKE-SECRET-123" not in str(caught.value)


def run_app_import(env: str) -> subprocess.CompletedProcess:
    """Start the app the way uvicorn does (import app.main) in a separate Python."""
    environment = {
        **os.environ,
        "ENV": env,
        "AUTH_MODE": "local",
        # Fakes override backend/.env, so real keys can never reach this test's output.
        "GEMINI_API_KEY": "fake-gemini-key",
        "GROQ_API_KEY": "fake-groq-key",
    }
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_app_refuses_to_start_in_production_with_local_auth():
    result = run_app_import("production")

    assert result.returncode != 0
    assert GUARD_MESSAGE in result.stderr
    assert "fake-gemini-key" not in result.stderr


def test_the_same_app_starts_in_development():
    # Control: proves the failure above comes from the guard, not a broken import.
    assert run_app_import("development").returncode == 0


# --- Seeding the local user --------------------------------------------------------


def test_seed_creates_the_local_user(db_session):
    user = ensure_local_user(db_session)

    assert user.email == LOCAL_USER_EMAIL == "local@studymate.dev"
    assert count_users(db_session) == 1


def test_seeding_twice_keeps_one_user(db_session):
    first = ensure_local_user(db_session)
    second = ensure_local_user(db_session)

    assert first.id == second.id
    assert count_users(db_session) == 1


def test_seed_script_seeds_the_configured_database(db_url, db_session):
    environment = {**os.environ, "DATABASE_URL": db_url}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.seed"],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert LOCAL_USER_EMAIL in result.stdout
    assert db_session.scalar(select(User.email)) == LOCAL_USER_EMAIL


# --- get_current_user() --------------------------------------------------------------

LOCAL_SETTINGS = Settings(_env_file=None, env="test", auth_mode="local")


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_current_user_is_the_seeded_local_user(db_session, host):
    seeded = ensure_local_user(db_session)

    user = get_current_user(request_from(host), LOCAL_SETTINGS, db_session)

    assert user.id == seeded.id


def test_current_user_explains_a_missing_seed(db_session):
    with pytest.raises(HTTPException) as caught:
        get_current_user(request_from("127.0.0.1"), LOCAL_SETTINGS, db_session)

    assert caught.value.status_code == 500
    assert "python -m scripts.seed" in caught.value.detail


@pytest.mark.parametrize("host", ["192.168.1.20", "203.0.113.5", None])
def test_local_mode_refuses_callers_from_other_machines(db_session, host):
    ensure_local_user(db_session)

    with pytest.raises(HTTPException) as caught:
        get_current_user(request_from(host), LOCAL_SETTINGS, db_session)

    assert caught.value.status_code == 403


def test_a_remote_request_gets_403_in_the_error_shape(client):
    # Same app and seeded database as `client`, but the request comes from another machine.
    with TestClient(app, client=("203.0.113.5", 50000)) as remote:
        response = remote.get("/api/conversations")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


# --- No endpoint takes user_id from the request -------------------------------------


def request_field_names() -> set[str]:
    """Every query/path/header parameter and JSON body field the API accepts."""
    spec = app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})
    names = set()
    for operations in spec["paths"].values():
        for operation in operations.values():
            names |= {parameter["name"] for parameter in operation.get("parameters", [])}
            for media in operation.get("requestBody", {}).get("content", {}).values():
                schema_name = media["schema"].get("$ref", "").split("/")[-1]
                names |= set(schemas.get(schema_name, {}).get("properties", {}))
    return names


def test_no_endpoint_accepts_user_id_from_the_request():
    names = request_field_names()

    assert "message" in names  # the scan really sees request bodies
    assert "user_id" not in names
