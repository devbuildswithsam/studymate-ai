"""Personal access tokens for MCP clients, and Bearer auth on /mcp. SMA-61 (guide 7.2).

Programs (MCP Inspector, Claude Desktop...) can't fill in a login form, and a browser
cookie on /mcp would make it a CSRF target. So in AUTH_MODE=jwt a program sends
`Authorization: Bearer <token>`: a long random token the user made on the Settings page.
Only its SHA-256 hash is stored. Written test-first.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import AccessToken, Task, User
from tests.auth_helpers import register

# The Host header the MCP server's DNS-rebinding protection accepts (see test_mcp_http.py).
MCP_URL = "http://127.0.0.1:8000"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": "2025-11-25",
}


def make_token(api, name="MCP Inspector", **extra) -> dict:
    response = api.post("/api/tokens", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def mcp(token: str | None = None, *, headers: dict | None = None, method="tools/list", params=None):
    """One JSON-RPC call to /mcp, like a program would make it (no cookies)."""
    all_headers = {**MCP_HEADERS, **(headers or {})}
    if token is not None:
        all_headers["Authorization"] = f"Bearer {token}"
    program = TestClient(app, base_url=MCP_URL, client=("127.0.0.1", 50000))
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return program.post("/mcp", json=body, headers=all_headers)


def tool_result(response) -> dict:
    content = response.json()["result"]
    return content.get("structuredContent") or json.loads(content["content"][0]["text"])


@pytest.fixture
def ada(jwt_api):
    """jwt_api logged in as Ada (the app's lifespan runs, so /mcp is up)."""
    register(jwt_api)
    return jwt_api


# --- Creating, listing and revoking tokens ------------------------------------------------------


def test_a_new_token_is_shown_once_and_only_its_hash_is_stored(ada, db_session):
    created = make_token(ada)

    token = created["token"]
    assert token.startswith("smat_") and len(token) >= 45  # prefix + 32 random bytes
    stored = db_session.scalar(select(AccessToken))
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(stored.__dict__)  # the token itself is nowhere in the database
    listed = ada.get("/api/tokens").json()
    assert "token" not in listed[0]  # never shown again
    assert listed[0]["prefix"] == token[:12]  # enough to recognise it
    assert listed[0]["name"] == "MCP Inspector"


@pytest.mark.parametrize("days", [30, 90, 365])
def test_a_token_expires_after_the_chosen_days(ada, days):
    created = make_token(ada, expires_in_days=days)

    expires = datetime.fromisoformat(created["expires_at"])
    expected = datetime.now(UTC) + timedelta(days=days)
    assert abs(expires - expected) < timedelta(minutes=1)


def test_the_default_expiry_is_90_days(ada):
    expires = datetime.fromisoformat(make_token(ada)["expires_at"])

    assert abs(expires - (datetime.now(UTC) + timedelta(days=90))) < timedelta(minutes=1)


@pytest.mark.parametrize(
    "body",
    [{"name": ""}, {"name": "x" * 101}, {"name": "ok", "expires_in_days": 7}],
    ids=["empty name", "name too long", "unknown expiry"],
)
def test_bad_input_is_refused(ada, body):
    assert ada.post("/api/tokens", json=body).status_code == 422


def test_at_most_10_tokens(ada):
    for number in range(10):
        make_token(ada, name=f"token {number}")

    response = ada.post("/api/tokens", json={"name": "one too many"})

    assert response.status_code == 409


def test_the_limit_is_per_user(ada, jwt_api):
    for number in range(10):
        make_token(ada, name=f"token {number}")
    jwt_api.cookies.clear()
    register(jwt_api, email="bob@example.com", name="Bob")

    assert jwt_api.post("/api/tokens", json={"name": "Bob's first"}).status_code == 201


def test_listed_times_say_they_are_utc(ada):
    # SQLite gives times back without a time zone. Sent like that, the browser would read
    # them as local time (5.5 hours off in India) and show "Expired" at the wrong moment.
    make_token(ada)

    listed = ada.get("/api/tokens").json()[0]

    for field in ("created_at", "expires_at"):
        assert datetime.fromisoformat(listed[field]).utcoffset() == timedelta(0), field


def test_deleting_a_token_revokes_it(ada, db_session):
    created = make_token(ada)

    assert ada.delete(f"/api/tokens/{created['id']}").status_code == 204

    assert ada.get("/api/tokens").json() == []
    assert mcp(created["token"]).status_code == 401  # it no longer opens /mcp


def test_another_users_token_cannot_be_seen_or_deleted(ada, jwt_api):
    adas = make_token(ada)
    jwt_api.cookies.clear()
    register(jwt_api, email="bob@example.com", name="Bob")

    assert jwt_api.get("/api/tokens").json() == []
    assert jwt_api.delete(f"/api/tokens/{adas['id']}").status_code == 404
    assert mcp(adas["token"]).status_code == 200  # Ada's token still works


def test_tokens_need_a_login(jwt_api):
    assert jwt_api.get("/api/tokens").status_code == 401


# --- /mcp in AUTH_MODE=jwt: every way in without a valid token is refused --------------------


def assert_refused(response):
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")  # says how to get in
    assert response.json()["error"]["code"] == "unauthorized"


def test_no_token(ada):
    assert_refused(mcp())


def test_another_scheme(ada):
    token = make_token(ada)["token"]

    assert_refused(mcp(headers={"Authorization": f"Basic {token}"}))


@pytest.mark.parametrize("token", ["smat_not-a-real-token-at-all-0000000000000", "", "x" * 2000])
def test_an_unknown_token(ada, token):
    assert_refused(mcp(headers={"Authorization": f"Bearer {token}"}))


def test_an_expired_token(ada, db_session):
    created = make_token(ada)
    row = db_session.get(AccessToken, created["id"])
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    assert_refused(mcp(created["token"]))


def test_a_session_cookie_is_not_a_token(ada):
    # /mcp takes Bearer tokens only: a cookie here would make it a CSRF target.
    program = TestClient(app, base_url=MCP_URL, client=("127.0.0.1", 50000))
    program.cookies.update(ada.cookies)
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

    assert_refused(program.post("/mcp", json=body, headers=MCP_HEADERS))


# --- A valid token acts for its owner, and only its owner ----------------------------------------


def test_a_valid_token_opens_mcp(ada):
    response = mcp(make_token(ada)["token"])

    assert response.status_code == 200
    assert "create_task" in {tool["name"] for tool in response.json()["result"]["tools"]}


def test_a_token_acts_only_for_its_owner(ada, jwt_api, db_session):
    adas_token = make_token(ada)["token"]
    ada.post("/api/tasks", json={"title": "Ada's task"})
    jwt_api.cookies.clear()
    register(jwt_api, email="bob@example.com", name="Bob")
    jwt_api.post("/api/tasks", json={"title": "Bob's task"})

    listed = mcp(adas_token, method="tools/call", params={"name": "list_tasks", "arguments": {}})
    created = mcp(
        adas_token,
        method="tools/call",
        params={"name": "create_task", "arguments": {"title": "Made over MCP"}},
    )

    assert [task["title"] for task in tool_result(listed)["result"]] == ["Ada's task"]
    assert created.status_code == 200
    made = db_session.scalar(select(Task).where(Task.title == "Made over MCP"))
    assert db_session.get(User, made.user_id).email == "ada@example.com"  # the token's owner
    assert made.created_by == "ai"


def test_using_a_token_records_when(ada, db_session):
    created = make_token(ada)
    assert created["last_used_at"] is None

    mcp(created["token"])

    db_session.expire_all()
    assert db_session.get(AccessToken, created["id"]).last_used_at is not None
    assert ada.get("/api/tokens").json()[0]["last_used_at"] is not None
