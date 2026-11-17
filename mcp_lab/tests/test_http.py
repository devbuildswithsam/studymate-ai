"""The same server and client over Streamable HTTP instead of stdio. SMA-38.

What changes is only the transport (a URL instead of a subprocess's stdin/stdout); the
tools, their schemas and their results must be exactly the same.
"""

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import client
import httpx2
import pytest

HERE = Path(__file__).resolve().parents[1]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def http_server(tmp_path):
    """server.py --http in a subprocess on a free port, stopped after the test."""
    port = free_port()
    env = {**client.server_params().env, "MCP_LAB_DB": str(tmp_path / "lab.db")}
    process = subprocess.Popen(
        [sys.executable, str(HERE / "server.py"), "--http", "--port", str(port)],
        cwd=HERE,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        for _ in range(100):  # wait up to ~10 s until it accepts connections
            if process.poll() is not None:
                raise RuntimeError(f"server.py --http exited with code {process.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("server.py --http did not open its port")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)


def tool_shapes(transcript) -> list:
    """The tools/list result: names, descriptions, input and output schemas."""
    reply = next(
        m.message
        for m in transcript
        if m.direction == "<-" and "tools" in m.message.get("result", {})
    )
    return reply["result"]["tools"]


@pytest.mark.anyio
async def test_the_same_client_works_over_http(http_server):
    transcript: list[client.WireMessage] = []

    results = await client.run_http(http_server, transcript)

    assert results.tool_names == ["add_task", "complete_task", "list_tasks"]
    assert results.added["title"] == "Finish thermodynamics notes"
    assert "1 pending" in results.summary
    assert "Finish thermodynamics notes" in results.plan


@pytest.mark.anyio
async def test_only_the_transport_changes(http_server, tmp_path):
    over_stdio: list[client.WireMessage] = []
    over_http: list[client.WireMessage] = []

    stdio_results = await client.run_stdio(client.server_params(tmp_path / "stdio.db"), over_stdio)
    http_results = await client.run_http(http_server, over_http)

    assert tool_shapes(over_http) == tool_shapes(over_stdio)  # same tools and schemas
    assert http_results.added == stdio_results.added  # same results
    assert http_results.pending == stdio_results.pending

    def methods(transcript):
        return [m.message.get("method") for m in transcript if m.direction == "->"]

    assert methods(over_http) == methods(over_stdio)  # same JSON-RPC conversation


def test_the_http_server_only_listens_on_this_computer():
    # --http binds 127.0.0.1, never 0.0.0.0: the lab has no login.
    source = (HERE / "server.py").read_text(encoding="utf-8")
    assert 'host="127.0.0.1"' in source
    assert "0.0.0.0" not in source


def test_main_accepts_a_url(http_server, capsys):
    client.main(["--url", http_server])

    out = capsys.readouterr().out
    assert "-> #1 initialize" in out
    assert "Every primitive worked" in out


def test_on_the_wire_a_request_is_one_http_post_with_json_rpc_inside(http_server):
    # No SDK here: plain HTTP, to see what the transport really sends.
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "raw-http", "version": "0"},
        },
    }
    response = httpx2.post(
        http_server,
        json=request,
        headers={"Accept": "application/json, text/event-stream"},
        timeout=10,
    )

    assert response.status_code == 200
    # The answer comes back as a server-sent event: "event: message" + "data: {json}".
    assert response.headers["content-type"].startswith("text/event-stream")
    data = next(line for line in response.text.splitlines() if line.startswith("data: "))
    reply = json.loads(data.removeprefix("data: "))
    assert reply["id"] == 1
    assert reply["result"]["serverInfo"]["name"] == "StudyMate MCP lab"
