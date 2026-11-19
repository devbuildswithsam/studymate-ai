"""/mcp inside the FastAPI app (Streamable HTTP, stateless). SMA-41, written test-first.

The endpoint resolves the user itself (local mode: the seeded user, this computer only),
puts it in the tool context, and only then hands the request to the MCP server.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.models import Task, User

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": "2025-11-25",
}
LOCAL = ("127.0.0.1", 50000)
NOTES = b"Entropy always increases in an isolated system, so heat flows from hot to cold."
BASE_URL = "http://127.0.0.1:8000"  # the Host header DNS-rebinding protection accepts


def rpc(http, method: str, params: dict | None = None, request_id: int = 1):
    body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
    return http.post("/mcp", json=body, headers=HEADERS)


def initialize(http):
    return rpc(
        http,
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    )


def test_the_apps_tools_are_listed_at_mcp(client):
    with TestClient(app, client=LOCAL, base_url=BASE_URL) as http:
        assert initialize(http).json()["result"]["serverInfo"]["name"] == "StudyMate"
        tools = rpc(http, "tools/list", request_id=2).json()["result"]["tools"]

    assert {t["name"] for t in tools} == {
        "create_task",
        "list_tasks",
        "update_task",
        "complete_task",
        "save_note",
        "search_notes",
        "search_documents",  # SMA-48
    }


def test_a_task_created_over_mcp_belongs_to_the_local_user_and_shows_on_the_board(
    client, db_session
):
    with TestClient(app, client=LOCAL, base_url=BASE_URL) as http:
        reply = rpc(
            http,
            "tools/call",
            {"name": "create_task", "arguments": {"title": "From MCP", "due_date": "2026-11-20"}},
        ).json()

    assert reply["result"]["isError"] is False
    task = db_session.get(Task, reply["result"]["structuredContent"]["id"])
    local_user = db_session.query(User).filter_by(email="local@studymate.dev").one()
    assert (task.user_id, task.created_by) == (local_user.id, "ai")
    board = client.get("/api/tasks").json()  # the same task through the normal API
    assert [(t["title"], t["created_by"]) for t in board] == [("From MCP", "ai")]


def test_an_injected_user_id_is_rejected_over_http(client, db_session):
    with TestClient(app, client=LOCAL, base_url=BASE_URL) as http:
        reply = rpc(
            http,
            "tools/call",
            {"name": "create_task", "arguments": {"title": "x", "user_id": "someone-else"}},
        ).json()

    assert reply["error"]["code"] == -32602
    assert "user_id" in reply["error"]["message"]
    assert db_session.query(Task).count() == 0


def test_mcp_refuses_other_computers_in_local_mode(client):
    # Local mode trusts the caller as the local user, so only this computer may call.
    with TestClient(app, client=("203.0.113.5", 50000), base_url=BASE_URL) as http:
        response = initialize(http)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_mcp_explains_a_missing_local_user(client, db_session):
    db_session.query(User).delete()
    db_session.commit()

    with TestClient(app, client=LOCAL, base_url=BASE_URL) as http:
        response = initialize(http)

    assert response.status_code == 500
    assert "python -m scripts.seed" in response.json()["error"]["message"]


def test_the_app_can_start_and_stop_many_times(client):
    # The MCP session manager can only run once per instance: the app builds a fresh
    # one at every start (the test suite starts the app hundreds of times).
    for _ in range(3):
        with TestClient(app, client=LOCAL, base_url=BASE_URL) as http:
            assert initialize(http).status_code == 200


def test_search_documents_over_mcp_uses_the_apps_embedding_settings(client):
    # The tests have no Gemini key: a correctly wired embedder can't reach the real API and
    # says so. ("isn't available" would mean no embedder was given to the tools at all.)
    client.post("/api/documents", files={"file": ("notes.md", NOTES, "text/markdown")})

    with TestClient(app, client=LOCAL, base_url=BASE_URL) as http:
        reply = rpc(
            http, "tools/call", {"name": "search_documents", "arguments": {"query": "entropy"}}
        ).json()["result"]

    assert reply["isError"] is True
    assert "GEMINI_API_KEY is not set" in reply["content"][0]["text"]
