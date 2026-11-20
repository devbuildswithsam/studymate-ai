"""CSRF protection: the Origin check and the double-submit token. SMA-58 (guide 9, ADR-0009).

The attack: you're logged in to StudyMate and open another website. That site makes your
browser send POST /api/notes to StudyMate, and the browser attaches your session cookie.

Two locks:
- Origin check: browsers say which site started a request. Unsafe requests (POST, PUT,
  PATCH, DELETE) from any site other than our frontend get 403. In both auth modes: in
  local mode the app trusts everything from this computer, the browser included.
- Double-submit token (AUTH_MODE=jwt): login also sets a `studymate_csrf` cookie that our
  JavaScript reads and sends back as the X-CSRF-Token header. Another site can make the
  browser SEND our cookies but can't READ them, so it can't fill in the header.
"""

import pytest
from sqlalchemy import func, select

from app.models import Note
from tests.auth_helpers import (
    CSRF_COOKIE,
    CSRF_HEADER,
    FRONTEND,
    register,
    set_cookie_header,
)

EVIL = "https://evil.example"


def notes_in_db(db_session) -> int:
    return db_session.scalar(select(func.count()).select_from(Note))


@pytest.fixture
def ada(jwt_api):
    """jwt_api, logged in as Ada (so it holds a session cookie and a CSRF cookie)."""
    register(jwt_api)
    return jwt_api


# --- The CSRF cookie -----------------------------------------------------------------------


def test_login_sets_a_csrf_cookie_that_javascript_can_read(jwt_api):
    response = register(jwt_api)

    line = set_cookie_header(response, CSRF_COOKIE).lower()
    assert "httponly" not in line  # our JavaScript must read it: that's how double-submit works
    for flag in ["secure", "samesite=lax", "path=/"]:
        assert flag in line
    assert len(jwt_api.cookies[CSRF_COOKIE]) >= 32  # long and random


def test_every_login_gets_a_new_csrf_token(jwt_api):
    register(jwt_api)
    first = jwt_api.cookies[CSRF_COOKIE]

    jwt_api.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": "correct horse battery"}
    )

    assert jwt_api.cookies[CSRF_COOKIE] != first


def test_me_restores_a_missing_csrf_cookie_and_keeps_an_existing_one(ada):
    existing = ada.cookies[CSRF_COOKIE]
    ada.get("/api/auth/me")
    assert ada.cookies[CSRF_COOKIE] == existing  # unchanged

    ada.cookies.delete(CSRF_COOKIE)
    ada.get("/api/auth/me")
    assert len(ada.cookies[CSRF_COOKIE]) >= 32  # the app can recover without a new login


def test_logout_deletes_the_csrf_cookie_too(ada):
    response = ada.post("/api/auth/logout")

    assert response.status_code == 204
    assert "max-age=0" in set_cookie_header(response, CSRF_COOKIE).lower()
    assert CSRF_COOKIE not in ada.cookies


# --- The double-submit token (AUTH_MODE=jwt) ------------------------------------------------


def test_our_frontend_can_write(ada, db_session):
    response = ada.post("/api/notes", json={"title": "Mine"}, headers={"Origin": FRONTEND})

    assert response.status_code == 201
    assert notes_in_db(db_session) == 1


@pytest.mark.parametrize(
    "header",
    [None, "wrong-token-of-a-reasonable-length-123456"],
    ids=["no header", "wrong header"],
)
def test_a_write_without_the_right_token_is_refused(ada, db_session, header):
    ada.auto_csrf = False  # act like another website: it can't read our cookies
    headers = {CSRF_HEADER: header} if header else {}

    response = ada.post("/api/notes", json={"title": "Forged"}, headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert notes_in_db(db_session) == 0  # refused before the route ran


def test_a_header_without_its_cookie_is_refused(ada):
    token = ada.cookies[CSRF_COOKIE]
    ada.cookies.delete(CSRF_COOKIE)

    response = ada.post("/api/notes", json={"title": "x"}, headers={CSRF_HEADER: token})

    assert response.status_code == 403


@pytest.mark.parametrize(
    "method, path",
    [
        ("POST", "/api/notes"),
        ("PATCH", "/api/notes/some-id"),
        ("PUT", "/api/conversations/some-id/documents"),
        ("DELETE", "/api/notes/some-id"),
        ("POST", "/api/auth/logout"),
    ],
)
def test_every_unsafe_method_needs_the_token(ada, method, path):
    ada.auto_csrf = False

    response = ada.request(method, path, json={})

    assert response.status_code == 403


@pytest.mark.parametrize("path", ["/api/notes", "/api/auth/me", "/api/conversations"])
def test_reading_needs_no_token(ada, path):
    # GET must never change anything, so it isn't a CSRF target.
    ada.auto_csrf = False

    assert ada.get(path).status_code == 200


def test_login_and_register_need_no_token(jwt_api):
    # There is no session yet, so there is no token to match. The Origin check still runs.
    jwt_api.auto_csrf = False

    assert register(jwt_api).status_code == 201
    jwt_api.cookies.clear()
    login = jwt_api.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": "correct horse battery"}
    )
    assert login.status_code == 200


def test_mcp_is_left_to_its_own_check(ada):
    # /mcp is for programs with Bearer tokens (SMA-61), not cookies: no CSRF check. In jwt
    # mode it answers 401 (its own refusal), not 403 from CSRF.
    ada.auto_csrf = False

    response = ada.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response.status_code == 401


# --- The Origin check (both modes) -----------------------------------------------------------


@pytest.mark.parametrize("origin", [EVIL, "null", "http://localhost:5174"])
def test_a_write_from_another_origin_is_refused_even_with_the_token(ada, db_session, origin):
    # "null" is what sandboxed pages and some redirects send. 5174 is another local app.
    response = ada.post("/api/notes", json={"title": "Forged"}, headers={"Origin": origin})

    assert response.status_code == 403
    assert notes_in_db(db_session) == 0


def test_without_an_origin_the_referer_is_checked(ada):
    response = ada.post("/api/notes", json={"title": "Forged"}, headers={"Referer": f"{EVIL}/page"})

    assert response.status_code == 403


def test_a_referer_from_our_frontend_is_fine(ada):
    response = ada.post(
        "/api/notes", json={"title": "Mine"}, headers={"Referer": f"{FRONTEND}/notes"}
    )

    assert response.status_code == 201


@pytest.mark.parametrize("path", ["/api/auth/login", "/api/auth/register"])
def test_login_csrf_is_refused(jwt_api, path):
    # Login CSRF: another site logs you in to ITS account, then sees what you type there.
    body = {"email": "ada@example.com", "password": "correct horse battery"}

    response = jwt_api.post(path, json=body, headers={"Origin": EVIL})

    assert response.status_code == 403


def test_local_mode_refuses_other_websites_too(client, db_session):
    # Local mode trusts every request from this computer, and the browser IS on this
    # computer: without this check any website could write to your StudyMate.
    response = client.post("/api/notes", json={"title": "Forged"}, headers={"Origin": EVIL})

    assert response.status_code == 403
    assert notes_in_db(db_session) == 0


def test_local_mode_needs_no_token(client):
    # No login in local mode, so no CSRF cookie: the Origin check is the lock.
    ok = client.post("/api/notes", json={"title": "Mine"}, headers={"Origin": FRONTEND})

    assert ok.status_code == 201
