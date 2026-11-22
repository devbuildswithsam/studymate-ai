"""Real accounts: register, login, logout, /me, and AUTH_MODE=jwt. SMA-57 (ADR-0009).

Written test-first. Every attack ADR-0009 names is a test here that must be refused:
expired, tampered, wrongly signed and "alg: none" tokens, guessing passwords, and asking
"does this email have an account?".
"""

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.config import BACKEND_DIR, Settings
from app.db.seed import LOCAL_USER_EMAIL
from app.models import User
from app.services import auth
from app.services.auth import (
    SESSION_COOKIE,
    LoginLimiter,
    create_session_token,
    hash_password,
    read_session_token,
    verify_password,
)
from tests.auth_helpers import SECRET, register, set_cookie_header

LOGIN_FAILED = "Email or password is incorrect."


# --- Settings and startup checks ------------------------------------------------------------


def test_jwt_mode_needs_a_secret():
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None, env="test", auth_mode="jwt")


def test_a_short_secret_is_refused_without_printing_it():
    with pytest.raises(ValidationError, match="at least 32") as caught:
        Settings(_env_file=None, env="test", auth_mode="jwt", jwt_secret="short-but-secret")

    assert "short-but-secret" not in str(caught.value)


@pytest.mark.parametrize("env", ["test", "production"])
def test_jwt_mode_with_a_long_secret_is_accepted(env):
    settings = Settings(_env_file=None, env=env, auth_mode="jwt", jwt_secret=SECRET)

    assert settings.auth_mode == "jwt"
    assert SECRET not in repr(settings)  # SecretStr: never shown in logs


def test_the_app_refuses_to_start_in_jwt_mode_without_a_secret():
    environment = {
        **os.environ,
        "ENV": "development",
        "AUTH_MODE": "jwt",
        "JWT_SECRET": "",  # overrides backend/.env
        "GEMINI_API_KEY": "fake-gemini-key",
        "GROQ_API_KEY": "fake-groq-key",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert "JWT_SECRET" in result.stderr
    assert "fake-gemini-key" not in result.stderr


# --- Passwords --------------------------------------------------------------------------------


def test_a_password_is_stored_as_an_argon2_hash():
    stored = hash_password("correct horse battery")

    assert stored.startswith("$argon2id$")
    assert "correct horse battery" not in stored
    assert verify_password("correct horse battery", stored)
    assert not verify_password("correct horse batter", stored)


def test_a_user_without_a_password_can_never_match():
    # The v1.0 local user has no password_hash.
    assert not verify_password("anything", None)


# --- Session tokens ----------------------------------------------------------------------------


def test_a_token_names_its_user_and_expires_after_8_hours():
    now = datetime.now(UTC)
    token = create_session_token("user-1", SECRET, now=now)

    claims = jwt.decode(token, SECRET, algorithms=["HS256"])
    assert claims["sub"] == "user-1"
    assert claims["exp"] - claims["iat"] == 8 * 60 * 60
    assert read_session_token(token, SECRET) == "user-1"


def tampered(token: str) -> str:
    """Swap the payload for one naming another user, keeping the old signature."""
    other = create_session_token("someone-else", SECRET)
    header, _, signature = token.split(".")
    return f"{header}.{other.split('.')[1]}.{signature}"


def bad_tokens() -> dict[str, str]:
    now = datetime.now(UTC)
    good = create_session_token("user-1", SECRET)
    return {
        "expired": create_session_token("user-1", SECRET, now=now - timedelta(hours=9)),
        "other secret": create_session_token("user-1", "another-secret-also-long-enough-xyz"),
        "tampered": tampered(good),
        "alg none": jwt.encode({"sub": "user-1", "exp": now + timedelta(hours=1)}, None, "none"),
        # Each of these lacks exactly one claim, so each proves its own `require` rule.
        "no expiry": jwt.encode({"sub": "user-1", "iat": now}, SECRET, algorithm="HS256"),
        "no issued-at": jwt.encode(
            {"sub": "user-1", "exp": now + timedelta(hours=1)}, SECRET, algorithm="HS256"
        ),
        "no user": jwt.encode(
            {"iat": now, "exp": now + timedelta(hours=1)}, SECRET, algorithm="HS256"
        ),
        "not a token": "hello",
    }


@pytest.mark.parametrize("kind", bad_tokens().keys())
def test_a_bad_token_names_nobody(kind):
    assert read_session_token(bad_tokens()[kind], SECRET) is None


# --- Guessing passwords ------------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_five_failures_block_the_next_try_for_15_minutes():
    clock = Clock()
    limiter = LoginLimiter(clock=clock)
    key = ("a@example.com", "127.0.0.1")

    for _ in range(5):
        assert limiter.allowed(*key)
        limiter.failed(*key)

    assert not limiter.allowed(*key)
    assert limiter.allowed("a@example.com", "10.0.0.9")  # another address
    assert limiter.allowed("b@example.com", "127.0.0.1")  # another account
    clock.now += timedelta(minutes=15, seconds=1)
    assert limiter.allowed(*key)


def test_a_successful_login_clears_the_failures():
    limiter = LoginLimiter(clock=Clock())
    for _ in range(4):
        limiter.failed("a@example.com", "127.0.0.1")

    limiter.succeeded("a@example.com", "127.0.0.1")
    for _ in range(4):
        limiter.failed("a@example.com", "127.0.0.1")

    assert limiter.allowed("a@example.com", "127.0.0.1")


# --- The API in AUTH_MODE=jwt ------------------------------------------------------------------


# The jwt_api fixture (conftest.py): the app in jwt mode, over https, acting like our
# frontend (it sends the CSRF header, SMA-58).


def cookie_header(response) -> str:
    return set_cookie_header(response, SESSION_COOKIE)


def test_register_creates_the_account_and_logs_in(jwt_api, db_session):
    response = register(jwt_api)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "ada@example.com"  # stored lower-case
    assert body["name"] == "Ada"
    assert "password" not in str(body)
    stored = db_session.scalar(select(User).where(User.email == "ada@example.com"))
    assert stored.password_hash.startswith("$argon2id$")
    assert jwt_api.get("/api/auth/me").json()["id"] == body["id"]


def test_the_session_cookie_has_every_safety_flag(jwt_api):
    header = cookie_header(register(jwt_api)).lower()

    assert header.startswith(f"{SESSION_COOKIE}=")
    for flag in ["httponly", "secure", "samesite=lax", "path=/", "max-age=28800"]:
        assert flag in header


def test_the_same_email_cannot_register_twice(jwt_api):
    register(jwt_api)

    response = register(jwt_api, email="ADA@example.com ")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    "email, password",
    [
        ("ada@example.com", "short12"),  # 7 characters
        ("ada@example.com", "x" * 129),
        ("not-an-email", "correct horse battery"),
        ("", "correct horse battery"),
    ],
    ids=["password too short", "password too long", "bad email", "empty email"],
)
def test_register_refuses_bad_input(jwt_api, email, password):
    response = register(jwt_api, email=email, password=password)

    assert response.status_code == 422
    assert SESSION_COOKIE not in response.headers.get("set-cookie", "")


def test_login_with_the_right_password(jwt_api):
    register(jwt_api)
    jwt_api.cookies.clear()

    response = jwt_api.post(
        "/api/auth/login", json={"email": "ADA@example.com", "password": "correct horse battery"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == "ada@example.com"
    assert "httponly" in cookie_header(response).lower()
    assert jwt_api.get("/api/auth/me").status_code == 200


def test_wrong_password_and_unknown_email_get_the_same_answer(jwt_api):
    register(jwt_api)
    jwt_api.cookies.clear()

    wrong = jwt_api.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": "nope-nope"}
    )
    unknown = jwt_api.post(
        "/api/auth/login", json={"email": "who@example.com", "password": "nope-nope"}
    )

    assert wrong.status_code == unknown.status_code == 401
    # The same answer word for word; only the request id differs (new on every request).
    same = {"code": "unauthorized", "message": LOGIN_FAILED}
    assert {**wrong.json()["error"], "request_id": None} == {**same, "request_id": None}
    assert {**unknown.json()["error"], "request_id": None} == {**same, "request_id": None}
    assert "set-cookie" not in wrong.headers


def test_an_unknown_email_still_checks_a_password_hash(jwt_api, monkeypatch):
    # Same work either way, so the response time doesn't reveal which emails exist.
    calls = []
    real_verify = auth.verify_password
    monkeypatch.setattr(auth, "verify_password", lambda p, h: calls.append(h) or real_verify(p, h))

    jwt_api.post("/api/auth/login", json={"email": "who@example.com", "password": "nope-nope"})

    assert len(calls) == 1
    assert calls[0] is not None and calls[0].startswith("$argon2id$")


def test_the_local_user_cannot_log_in(jwt_api, db_session):
    db_session.add(User(email=LOCAL_USER_EMAIL, name="Local user"))  # no password
    db_session.commit()

    response = jwt_api.post(
        "/api/auth/login", json={"email": LOCAL_USER_EMAIL, "password": "anything-at-all"}
    )

    assert response.status_code == 401


@pytest.mark.parametrize("email", [LOCAL_USER_EMAIL, "who@example.com"])
def test_the_dummy_password_never_logs_anyone_in(jwt_api, db_session, email):
    # The dummy hash's password is in the source code. It must not open an account without
    # a password (the local user) or log in as nobody.
    db_session.add(User(email=LOCAL_USER_EMAIL, name="Local user"))
    db_session.commit()

    response = jwt_api.post(
        "/api/auth/login", json={"email": email, "password": auth.DUMMY_PASSWORD}
    )

    assert response.status_code == 401


def test_too_many_wrong_passwords_are_blocked_even_with_the_right_one(jwt_api):
    register(jwt_api)
    jwt_api.cookies.clear()
    for _ in range(5):
        jwt_api.post("/api/auth/login", json={"email": "ada@example.com", "password": "wrong-pw"})

    response = jwt_api.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": "correct horse battery"}
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"


def test_logout_deletes_the_cookie(jwt_api):
    register(jwt_api)

    response = jwt_api.post("/api/auth/logout")

    assert response.status_code == 204
    assert "max-age=0" in cookie_header(response).lower()
    assert jwt_api.get("/api/auth/me").status_code == 401


def test_without_a_cookie_every_api_route_answers_401(jwt_api):
    for path in ["/api/auth/me", "/api/conversations", "/api/notes", "/api/tasks"]:
        response = jwt_api.get(path)

        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "unauthorized"


def test_a_cookie_set_by_hand_is_really_sent(jwt_api):
    # Control for the test below: a good token set the same way is accepted, so a 401
    # there comes from the bad token, not from a cookie that never arrived.
    user_id = register(jwt_api).json()["id"]
    jwt_api.cookies.clear()
    jwt_api.cookies.set(SESSION_COOKIE, create_session_token(user_id, SECRET))

    assert jwt_api.get("/api/auth/me").status_code == 200


@pytest.mark.parametrize("kind", bad_tokens().keys())
def test_a_bad_cookie_is_refused(jwt_api, kind):
    register(jwt_api)
    jwt_api.cookies.clear()
    jwt_api.cookies.set(SESSION_COOKIE, bad_tokens()[kind])

    assert jwt_api.get("/api/auth/me").status_code == 401


def test_a_token_for_a_deleted_user_is_refused(jwt_api, db_session):
    user_id = register(jwt_api).json()["id"]
    db_session.delete(db_session.get(User, user_id))
    db_session.commit()

    assert jwt_api.get("/api/auth/me").status_code == 401


def test_a_logged_in_user_only_sees_their_own_data(jwt_api):
    register(jwt_api)
    jwt_api.post("/api/notes", json={"title": "Ada's note"})
    jwt_api.cookies.clear()
    register(jwt_api, email="bob@example.com", name="Bob")

    assert jwt_api.get("/api/notes").json() == []


def test_mcp_refuses_a_logged_in_browser_without_a_token(jwt_api):
    # /mcp takes personal access tokens only (SMA-61), never the session cookie.
    register(jwt_api)
    response = jwt_api.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response.status_code == 401


# --- The API in AUTH_MODE=local ----------------------------------------------------------------


def test_me_is_the_local_user_in_local_mode(client):
    assert client.get("/api/auth/me").json()["email"] == LOCAL_USER_EMAIL


@pytest.mark.parametrize("path", ["/api/auth/register", "/api/auth/login"])
def test_accounts_are_off_in_local_mode(client, path):
    response = client.post(path, json={"email": "a@example.com", "password": "long enough pw"})

    assert response.status_code == 400
    assert "AUTH_MODE=local" in response.json()["error"]["message"]


def test_a_damaged_password_hash_is_a_failed_login_not_a_crash():
    """SMA-69: a broken row (edited by hand, an unknown algorithm) must never let anyone in."""
    assert verify_password("anything", "not-a-real-hash") is False
    assert verify_password("anything", "$argon2id$v=19$m=1,t=1,p=1$broken") is False
