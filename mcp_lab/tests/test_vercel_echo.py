"""The one-tool echo server meant for Vercel (no data). SMA-38.

Tested locally as a plain ASGI app: the MCP protocol, and which Host headers it accepts.
"""

import importlib

import pytest
from mcp import Client
from starlette.testclient import TestClient

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


def load_echo(monkeypatch, **vercel_env):
    """Import vercel_echo/main.py fresh, with Vercel's environment variables set."""
    for name in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in vercel_env.items():
        monkeypatch.setenv(name, value)
    import vercel_echo.main as module

    return importlib.reload(module)


@pytest.mark.anyio
async def test_the_echo_tool_answers(monkeypatch):
    echo = load_echo(monkeypatch)
    async with Client(echo.server) as client:
        tools = (await client.list_tools()).tools
        result = await client.call_tool("echo", {"text": "hello from the lab"})

    assert [t.name for t in tools] == ["echo"]
    assert result.structured_content == {"result": "hello from the lab"}


@pytest.mark.anyio
async def test_echo_keeps_messages_short(monkeypatch):
    echo = load_echo(monkeypatch)
    async with Client(echo.server) as client:
        result = await client.call_tool("echo", {"text": "x" * 501})

    assert result.is_error  # a public endpoint: no unlimited input


def post_initialize(app, *hosts: str) -> list[int]:
    """POST an MCP initialize with each Host header; returns the status codes.

    One TestClient for all of them: the app's session manager starts once per app
    instance (on Vercel, once per cold start)."""
    with TestClient(app) as http:
        return [
            http.post("/mcp", json=INITIALIZE, headers={**HEADERS, "Host": host}).status_code
            for host in hosts
        ]


def test_vercel_hosts_are_allowed(monkeypatch):
    echo = load_echo(
        monkeypatch,
        VERCEL_URL="studymate-echo-abc123.vercel.app",
        VERCEL_PROJECT_PRODUCTION_URL="studymate-echo.vercel.app",
    )

    statuses = post_initialize(
        echo.app, "studymate-echo.vercel.app", "studymate-echo-abc123.vercel.app"
    )

    assert statuses == [200, 200]


def test_the_answer_is_plain_json(monkeypatch):
    # json_response=True: no server-sent-event stream, which suits serverless.
    echo = load_echo(monkeypatch)
    with TestClient(echo.app) as http:
        response = http.post("/mcp", json=INITIALIZE, headers={**HEADERS, "Host": "127.0.0.1:8000"})

    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["result"]["serverInfo"]["name"] == "StudyMate echo"


def test_other_hosts_are_refused(monkeypatch):
    # DNS-rebinding protection: only our own addresses.
    echo = load_echo(monkeypatch, VERCEL_PROJECT_PRODUCTION_URL="studymate-echo.vercel.app")

    assert post_initialize(echo.app, "evil.example.com") == [421]


def test_without_vercel_it_only_accepts_localhost(monkeypatch):
    echo = load_echo(monkeypatch)

    assert post_initialize(echo.app, "127.0.0.1:8000", "studymate-echo.vercel.app") == [200, 421]


# --- Our client against the echo app, served for real by uvicorn ---------------------


@pytest.fixture
def echo_url():
    """vercel_echo/main.py served by uvicorn on a free port (what Vercel runs, locally)."""
    import socket
    import subprocess
    import sys
    import time

    import client

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "vercel_echo.main:app", "--port", str(port)],
        cwd=client.HERE,
        env=client.get_default_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError(f"uvicorn exited with code {process.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("uvicorn did not open its port")
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.mark.anyio
async def test_our_client_calls_the_echo_tool_over_http(echo_url):
    import client

    transcript: list[client.WireMessage] = []
    reply = await client.call_echo(echo_url, "hello from the lab", transcript)

    assert reply == "hello from the lab"
    sent = [m.message.get("method") for m in transcript if m.direction == "->"]
    assert sent == ["initialize", "notifications/initialized", "tools/list", "tools/call"]


def test_main_echo_mode_prints_the_reply(echo_url, capsys):
    import client

    client.main(["--url", echo_url, "--echo", "hi"])

    out = capsys.readouterr().out
    assert "-> #3 tools/call" in out
    assert "Echo replied: hi" in out


def test_get_is_refused_at_once_instead_of_held_open(monkeypatch):
    # In Streamable HTTP a GET opens a server-to-client event stream. This stateless echo
    # server never sends one, and on Vercel an open GET keeps a function running (and
    # uses the free quota). So: 405 immediately.
    echo = load_echo(monkeypatch)
    with TestClient(echo.app) as http:
        response = http.get(
            "/mcp", headers={"Accept": "text/event-stream", "Host": "127.0.0.1:8000"}
        )

    assert response.status_code == 405
    assert response.headers["allow"] == "POST"
