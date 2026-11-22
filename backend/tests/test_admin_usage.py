"""The admin usage view: AI calls, failures and tokens per model and per day (SMA-68).

Admins are listed by email in ADMIN_EMAILS (backend/.env). In AUTH_MODE=local the one
local user is the admin (it's your own computer). Everyone else gets 403.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.config import get_settings
from app.main import app
from app.models import LLMCall, User
from tests.auth_helpers import jwt_settings, register

NOW = datetime.now(UTC)


def call(db, user, model, status="ok", tokens=(10, 5), days_ago=0, provider="groq"):
    db.add(
        LLMCall(
            user_id=user.id,
            provider=provider,
            model=model,
            mode="general",
            status=status,
            error_type=None if status == "ok" else "timeout",
            tokens_in=tokens[0] if status == "ok" else None,
            tokens_out=tokens[1] if status == "ok" else None,
            created_at=NOW - timedelta(days=days_ago),
        )
    )


@pytest.fixture
def calls(client, db_session):
    """Calls by two users on two models over three days."""
    alice, bob = User(email="alice@example.com"), User(email="bob@example.com")
    db_session.add_all([alice, bob])
    db_session.flush()
    call(db_session, alice, "gpt-oss")
    call(db_session, bob, "gpt-oss", tokens=(100, 50))
    call(db_session, bob, "gpt-oss", status="error")
    call(db_session, alice, "gemini", provider="gemini", tokens=(7, 3))
    call(db_session, alice, "gpt-oss", days_ago=1)
    call(db_session, alice, "gpt-oss", days_ago=40)  # outside the last 30 days
    db_session.commit()


def test_calls_failures_and_tokens_per_day_and_model(client, calls):
    response = client.get("/api/admin/usage")

    assert response.status_code == 200
    usage = response.json()
    today, yesterday = NOW.date().isoformat(), (NOW - timedelta(days=1)).date().isoformat()
    assert usage["days"] == 30
    assert usage["rows"] == [  # newest day first, then by model
        {
            "day": today,
            "provider": "gemini",
            "model": "gemini",
            "calls": 1,
            "failures": 0,
            "tokens_in": 7,
            "tokens_out": 3,
        },
        {
            "day": today,
            "provider": "groq",
            "model": "gpt-oss",
            "calls": 3,
            "failures": 1,
            "tokens_in": 110,
            "tokens_out": 55,
        },
        {
            "day": yesterday,
            "provider": "groq",
            "model": "gpt-oss",
            "calls": 1,
            "failures": 0,
            "tokens_in": 10,
            "tokens_out": 5,
        },
    ]
    assert usage["totals"] == {"calls": 5, "failures": 1, "tokens_in": 127, "tokens_out": 63}


def test_no_user_is_named_in_the_usage(client, calls):
    text = client.get("/api/admin/usage").text

    assert "alice" not in text and "bob" not in text and "user" not in text


def test_the_period_can_be_chosen_within_limits(client, calls):
    assert client.get("/api/admin/usage", params={"days": 90}).json()["totals"]["calls"] == 6
    assert client.get("/api/admin/usage", params={"days": 0}).status_code == 422
    assert client.get("/api/admin/usage", params={"days": 366}).status_code == 422


def test_the_local_user_is_the_admin_in_local_mode(client):
    assert client.get("/api/auth/me").json()["is_admin"] is True


# --- Real accounts: only the emails in ADMIN_EMAILS ------------------------------------------


@pytest.fixture
def admins_are(jwt_api, db_url):
    def set_admins(emails: str) -> None:
        settings = jwt_settings(db_url).model_copy(update={"admin_emails": emails})
        app.dependency_overrides[get_settings] = lambda: settings

    return set_admins


def test_a_normal_user_gets_403(jwt_api, admins_are):
    admins_are("someone.else@example.com")
    register(jwt_api)

    response = jwt_api.get("/api/admin/usage")

    assert response.status_code == 403
    assert jwt_api.get("/api/auth/me").json()["is_admin"] is False


def test_nobody_is_admin_when_the_list_is_empty(jwt_api, admins_are):
    admins_are("")
    register(jwt_api)

    assert jwt_api.get("/api/admin/usage").status_code == 403


def test_an_admin_email_sees_the_usage_whatever_its_capitals(jwt_api, admins_are):
    admins_are(" teacher@example.com , ADA@example.COM ")
    register(jwt_api, email="Ada@Example.com")

    assert jwt_api.get("/api/admin/usage").status_code == 200
    assert jwt_api.get("/api/auth/me").json()["is_admin"] is True


def test_without_a_session_it_is_401(jwt_api, admins_are):
    admins_are("ada@example.com")

    assert jwt_api.get("/api/admin/usage").status_code == 401
