"""The lab client: starts the real server.py over stdio and drives every primitive. SMA-37.

These tests start a real subprocess (no Inspector): what the client sees is what crosses
the wire.
"""

import client
import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def run(tmp_path):
    """Run the client's whole demo against a fresh lab.db; returns (results, transcript)."""
    transcript: list[client.WireMessage] = []
    results = await client.run_stdio(client.server_params(tmp_path / "lab.db"), transcript)
    return results, transcript


def requests(transcript):
    return [m.message for m in transcript if m.direction == "->" and "id" in m.message]


def responses(transcript):
    return [m.message for m in transcript if m.direction == "<-" and "id" in m.message]


@pytest.mark.anyio
async def test_the_client_drives_every_primitive(run):
    results, _ = run

    assert results.server_name == "StudyMate MCP lab"
    assert results.tool_names == ["add_task", "complete_task", "list_tasks"]
    assert results.added["title"] == "Finish thermodynamics notes"
    assert [t["title"] for t in results.pending] == ["Finish thermodynamics notes"]
    assert "1 pending" in results.summary
    assert "Finish thermodynamics notes" in results.plan


@pytest.mark.anyio
async def test_the_wire_shows_the_json_rpc_conversation_in_order(run):
    _, transcript = run

    sent = [m.message.get("method") for m in transcript if m.direction == "->"]
    assert sent == [
        "initialize",
        "notifications/initialized",  # a notification: no id, no reply
        "tools/list",
        "tools/call",  # add_task
        "tools/call",  # list_tasks
        "resources/list",
        "resources/read",
        "prompts/list",
        "prompts/get",
    ]


@pytest.mark.anyio
async def test_every_request_gets_a_response_with_the_same_id_and_no_error(run):
    _, transcript = run

    sent_ids = [r["id"] for r in requests(transcript)]
    answered = {r["id"]: r for r in responses(transcript)}

    assert sent_ids == sorted(set(sent_ids))  # unique, increasing
    assert set(answered) == set(sent_ids)
    assert all("result" in r and "error" not in r for r in answered.values())
    assert all(m.message["jsonrpc"] == "2.0" for m in transcript)


@pytest.mark.anyio
async def test_initialize_introduces_both_sides(run):
    _, transcript = run
    initialize = requests(transcript)[0]
    reply = responses(transcript)[0]

    assert initialize["method"] == "initialize"
    assert {"protocolVersion", "capabilities", "clientInfo"} <= set(initialize["params"])
    assert initialize["params"]["clientInfo"]["name"] == "studymate-mcp-lab-client"
    assert reply["result"]["serverInfo"]["name"] == "StudyMate MCP lab"
    # The server announces what it offers; a client should only use those.
    assert {"tools", "resources", "prompts"} <= set(reply["result"]["capabilities"])


@pytest.mark.anyio
async def test_tools_call_sends_the_tool_name_and_arguments(run):
    _, transcript = run
    call = next(r for r in requests(transcript) if r["method"] == "tools/call")
    reply = next(r for r in responses(transcript) if r["id"] == call["id"])

    assert call["params"]["name"] == "add_task"
    assert call["params"]["arguments"] == {
        "title": "Finish thermodynamics notes",
        "due_date": "2026-11-22",
        "priority": "high",
    }
    assert reply["result"]["isError"] is False
    assert reply["result"]["structuredContent"]["title"] == "Finish thermodynamics notes"


@pytest.mark.anyio
async def test_the_server_does_not_inherit_the_clients_whole_environment(tmp_path, monkeypatch):
    # Secrets in the client's environment must not leak into a server it starts.
    monkeypatch.setenv("SOME_SECRET_KEY", "do-not-pass")
    params = client.server_params(tmp_path / "lab.db")

    assert "SOME_SECRET_KEY" not in params.env
    assert params.env["MCP_LAB_DB"] == str(tmp_path / "lab.db")


def test_main_prints_the_wire_messages(tmp_path, capsys):
    client.main(["--db", str(tmp_path / "lab.db")])

    out = capsys.readouterr().out
    assert "-> #1 initialize" in out
    assert "<- #1 result" in out
    assert "-> notifications/initialized" in out
    assert '"name": "add_task"' in out  # the raw JSON is printed
    assert "Every primitive worked" in out
