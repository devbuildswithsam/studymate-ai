"""JSON logs with a request id, and nothing secret in them (SMA-68), test-first."""

import io
import json
import logging

import pytest

from app.db.session import make_engine
from app.logs import HANDLER_NAME, configure_logging, redact
from app.services.llm.exceptions import ProviderUnavailableError
from app.services.llm.fake import FakeProvider
from tests.auth_helpers import register
from tests.test_conversations_api import new_conversation, use_fakes


@pytest.fixture
def logs():
    """Everything logged during the test, as JSON lines (the app's real formatter)."""
    stream = io.StringIO()
    configure_logging(stream)
    lines = lambda: [json.loads(line) for line in stream.getvalue().splitlines()]  # noqa: E731
    yield lines
    root = logging.getLogger()
    for handler in [h for h in root.handlers if h.get_name() == HANDLER_NAME]:
        root.removeHandler(handler)


# --- The request id ---------------------------------------------------------------------------


def test_every_response_has_its_own_request_id(client):
    first = client.get("/api/health").headers["x-request-id"]
    second = client.get("/api/health").headers["x-request-id"]

    assert len(first) == 32 and first != second


def test_an_id_from_a_proxy_is_kept_if_harmless(client):
    kept = client.get("/api/health", headers={"X-Request-ID": "edge-1234abcd"})
    forged = client.get("/api/health", headers={"X-Request-ID": "x\nERROR fake log line"})

    assert kept.headers["x-request-id"] == "edge-1234abcd"
    assert forged.headers["x-request-id"] != "x\nERROR fake log line"


@pytest.mark.parametrize(
    "method, path, status",
    [("GET", "/api/nothing-here", 404), ("POST", "/api/notes", 422)],
)
def test_error_bodies_carry_the_request_id(client, method, path, status):
    response = client.request(method, path, json={})

    assert response.status_code == status
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_a_crash_says_which_request_it_was(client, logs):
    use_fakes({"main": FakeProvider(error=ZeroDivisionError("a bug")), "backup": FakeProvider()})
    chat = new_conversation(client)
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 50000)) as c:
        response = c.post(f"/api/conversations/{chat}/messages", json={"message": "Hi"})

    request_id = response.headers["x-request-id"]
    assert response.status_code == 500
    assert response.json()["error"]["request_id"] == request_id
    crash = [line for line in logs() if line["level"] == "ERROR"]
    assert crash and crash[0]["request_id"] == request_id
    assert "ZeroDivisionError" in crash[0]["exception"]


# --- The log lines ----------------------------------------------------------------------------


def test_one_json_access_line_per_request_without_the_query_string(client, logs):
    response = client.get("/api/notes/search", params={"q": "my private search words"})

    [line] = [entry for entry in logs() if entry["logger"] == "studymate.access"]
    assert line["request_id"] == response.headers["x-request-id"]
    assert (line["method"], line["path"], line["status"]) == ("GET", "/api/notes/search", 200)
    assert isinstance(line["duration_ms"], int)
    assert "private search words" not in json.dumps(logs())


def test_lines_written_inside_a_request_carry_its_id_even_from_helper_threads(client, logs):
    # The FallbackManager logs the failed model from the thread that ran the AI call.
    down = FakeProvider(error=ProviderUnavailableError("down", "fake"))
    use_fakes({"main": down, "backup": FakeProvider(replies=["Backup answer."])})
    chat = new_conversation(client)

    response = client.post(f"/api/conversations/{chat}/messages", json={"message": "Hi"})

    [warning] = [line for line in logs() if line["level"] == "WARNING"]
    assert "main failed" in warning["message"]
    assert warning["request_id"] == response.headers["x-request-id"]


def test_a_streamed_answer_logs_with_its_request_id(client, logs):
    down = FakeProvider(error=ProviderUnavailableError("down", "fake"))
    use_fakes({"main": down, "backup": FakeProvider(replies=["Backup answer."])})
    chat = new_conversation(client)

    response = client.post(
        f"/api/conversations/{chat}/messages",
        json={"message": "Hi"},
        headers={"accept": "text/event-stream"},
    )

    [warning] = [line for line in logs() if line["level"] == "WARNING"]
    assert warning["request_id"] == response.headers["x-request-id"]


# --- Nothing secret -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "Authorization: Bearer abc.def-123",
        "token smat_Zx9QmW3r8kLpTn2v",
        "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl",
        "groq gsk_AbCdEf1234567890",
        "gemini AIzaSyA1234567890abcdef",
        "password=hunter2-correct-horse",
    ],
)
def test_anything_that_looks_secret_is_hidden(secret):
    hidden = redact(secret)

    for part in (
        "abc.def-123",
        "Zx9QmW3r8kLpTn2v",
        "c2lnbmF0dXJl",
        "AbCdEf1234567890",
        "SyA1234567890abcdef",
        "hunter2-correct-horse",
    ):
        assert part not in hidden


def test_a_whole_session_logs_no_password_token_or_document_text(jwt_api, logs):
    password = "Sup3r-secret passphrase"
    register(jwt_api, password=password)
    jwt_api.post("/api/auth/logout")
    jwt_api.post("/api/auth/login", json={"email": "ada@example.com", "password": password})
    jwt_api.post("/api/auth/login", json={"email": "ada@example.com", "password": "wrong guess!"})
    jwt_api.post("/api/auth/login", json={"email": "ada@example.com", "password": password})
    token = jwt_api.post("/api/tokens", json={"name": "Desktop"}).json()["token"]
    document = b"# Private notes\n\nMy secret revision plan for the thermodynamics exam."
    jwt_api.post("/api/documents", files={"file": ("plan.md", document, "text/markdown")})
    jwt_api.post("/mcp", headers={"Authorization": f"Bearer {token}"}, json={})
    session = jwt_api.cookies.get("studymate_session")

    written = json.dumps(logs())

    assert logs(), "the session should have produced log lines"
    for secret in (password, "wrong guess!", token, session, "secret revision plan"):
        assert secret not in written


def test_database_errors_never_show_the_values():
    # SQLAlchemy puts the statement's values ("[parameters: ...]") in its error messages,
    # which end up in tracebacks: a password hash or a document's text could leak.
    assert make_engine("sqlite://").hide_parameters is True


class ChattyProvider(FakeProvider):
    """Logs from INSIDE the AI call, which runs in the FallbackManager's helper thread."""

    def chat(self, messages, options=None):
        logging.getLogger("tests.provider").info("asking the model")
        return super().chat(messages, options)


def test_lines_from_inside_the_ai_call_carry_the_request_id(client, logs):
    use_fakes({"main": ChattyProvider(replies=["Hi."]), "backup": FakeProvider()})
    chat = new_conversation(client)

    response = client.post(f"/api/conversations/{chat}/messages", json={"message": "Hi"})

    [line] = [entry for entry in logs() if entry["logger"] == "tests.provider"]
    assert line["request_id"] == response.headers["x-request-id"]


def test_the_app_owns_the_root_logger_when_it_starts(monkeypatch):
    """The MCP library calls logging.basicConfig(): without this, every line twice."""
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", list(root.handlers))  # the real list comes back after
    plain = logging.StreamHandler(io.StringIO())
    root.addHandler(plain)

    configure_logging()  # as at startup: no stream given

    assert plain not in root.handlers
    assert [h.get_name() for h in root.handlers] == [HANDLER_NAME]
