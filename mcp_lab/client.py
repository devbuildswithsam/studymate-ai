"""MCP lab client (Stage 3a, SMA-37/38): drives the lab server and shows the raw JSON-RPC.

It starts the server as a subprocess, then talks to it through the SDK's ClientSession:
initialize, list_tools, call_tool, list/read a resource, list/get a prompt. Every message
that crosses the wire is recorded and printed, so you see the protocol itself.

From mcp_lab/ with its venv:
    .venv\\Scripts\\python client.py              (uses lab.db next to server.py)
    .venv\\Scripts\\python client.py --db C:\\...\\demo.db
    .venv\\Scripts\\python client.py --url http://127.0.0.1:8765/mcp   (server.py --http)
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import anyio
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import get_default_environment, stdio_client
from mcp.client.streamable_http import streamable_http_client

HERE = Path(__file__).resolve().parent


# --- Recording the wire ------------------------------------------------------------


@dataclass
class WireMessage:
    direction: Literal["->", "<-"]  # -> client to server, <- server to client
    message: dict[str, Any]  # the JSON-RPC message, exactly as sent


def as_json(message) -> dict[str, Any]:
    """A JSON-RPC message as the plain JSON that travels on the wire."""
    return message.model_dump(by_alias=True, exclude_none=True, mode="json")


class TapRead:
    """Wraps the stream of messages FROM the server: records each one, changes nothing."""

    def __init__(self, inner, transcript: list[WireMessage]):
        self.inner, self.transcript = inner, transcript

    def _record(self, item):
        if not isinstance(item, Exception):  # transports pass errors through the stream too
            self.transcript.append(WireMessage("<-", as_json(item.message)))
        return item

    async def receive(self):
        return self._record(await self.inner.receive())

    def __aiter__(self):
        return self

    async def __anext__(self):
        return self._record(await self.inner.__anext__())

    async def aclose(self):
        await self.inner.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return await self.inner.__aexit__(*exc_info)


class TapWrite:
    """Wraps the stream of messages TO the server: records each one, changes nothing."""

    def __init__(self, inner, transcript: list[WireMessage]):
        self.inner, self.transcript = inner, transcript

    async def send(self, item, /):
        self.transcript.append(WireMessage("->", as_json(item.message)))
        await self.inner.send(item)

    async def aclose(self):
        await self.inner.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return await self.inner.__aexit__(*exc_info)


# --- Driving every primitive ----------------------------------------------------------


@dataclass
class DemoResults:
    server_name: str = ""
    tool_names: list[str] = field(default_factory=list)
    added: dict[str, Any] = field(default_factory=dict)
    pending: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    plan: str = ""


def server_params(db_path: Path | None = None) -> StdioServerParameters:
    """How to start server.py. Only a safe minimum of environment variables is passed on:
    a server must not inherit everything the client has (API keys, for example)."""
    env = get_default_environment()
    if db_path is not None:
        env["MCP_LAB_DB"] = str(db_path)
    return StdioServerParameters(
        command=sys.executable, args=[str(HERE / "server.py")], env=env, cwd=str(HERE)
    )


def tool_data(result: types.CallToolResult) -> Any:
    if result.is_error:
        raise RuntimeError(result.content[0].text)
    return result.structured_content


async def demo(session: ClientSession) -> DemoResults:
    """Use every MCP primitive once, like an AI app would."""
    results = DemoResults()
    init = await session.initialize()  # handshake: versions, names, capabilities
    results.server_name = init.server_info.name

    tools = await session.list_tools()  # tools/list: names, descriptions, JSON Schemas
    results.tool_names = sorted(t.name for t in tools.tools)

    results.added = tool_data(  # tools/call
        await session.call_tool(
            "add_task",
            {"title": "Finish thermodynamics notes", "due_date": "2026-11-22", "priority": "high"},
        )
    )
    results.pending = tool_data(await session.call_tool("list_tasks", {}))["result"]

    resources = await session.list_resources()  # resources/list, then resources/read
    summary = await session.read_resource(resources.resources[0].uri)
    results.summary = summary.contents[0].text

    prompts = await session.list_prompts()  # prompts/list, then prompts/get
    prompt = await session.get_prompt(prompts.prompts[0].name, {"hours_available": "2"})
    results.plan = prompt.messages[0].content.text
    return results


async def run_session(read, write, transcript: list[WireMessage]) -> DemoResults:
    """The same session and demo for every transport: only (read, write) differ."""
    client_info = types.Implementation(name="studymate-mcp-lab-client", version="0.1.0")
    session = ClientSession(
        TapRead(read, transcript), TapWrite(write, transcript), client_info=client_info
    )
    async with session:
        return await demo(session)


async def run_stdio(params: StdioServerParameters, transcript: list[WireMessage]) -> DemoResults:
    """Start the server as a subprocess and run the demo over its stdin/stdout."""
    async with stdio_client(params) as (read, write):
        return await run_session(read, write, transcript)


async def run_http(url: str, transcript: list[WireMessage]) -> DemoResults:
    """Run the demo against a server that is already running at `url` (SMA-38).
    Each JSON-RPC message becomes an HTTP POST to that URL."""
    async with streamable_http_client(url) as (read, write):
        return await run_session(read, write, transcript)


async def call_echo(url: str, text: str, transcript: list[WireMessage]) -> str:
    """Call the one-tool echo server (vercel_echo/, deployed on Vercel) over HTTP."""
    async with streamable_http_client(url) as (read, write):
        client_info = types.Implementation(name="studymate-mcp-lab-client", version="0.1.0")
        session = ClientSession(
            TapRead(read, transcript), TapWrite(write, transcript), client_info=client_info
        )
        async with session:
            await session.initialize()
            await session.list_tools()
            return tool_data(await session.call_tool("echo", {"text": text}))["result"]


# --- Printing -------------------------------------------------------------------------


def describe(wire: WireMessage) -> str:
    """'-> #3 tools/call', '<- #3 result', '-> notifications/initialized'..."""
    message = wire.message
    if "method" in message:
        number = f"#{message['id']} " if "id" in message else ""
        return f"{wire.direction} {number}{message['method']}"
    kind = "error" if "error" in message else "result"
    return f"{wire.direction} #{message.get('id')} {kind}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Drive the MCP lab server and show the wire.")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--db", type=Path, help="stdio: lab database file (default: lab.db)")
    where.add_argument("--url", help="HTTP: a running server, e.g. http://127.0.0.1:8765/mcp")
    parser.add_argument("--echo", metavar="TEXT", help="with --url: call the echo server's tool")
    args = parser.parse_args(argv)
    if args.echo and not args.url:
        parser.error("--echo needs --url (the echo server runs over HTTP)")

    transcript: list[WireMessage] = []
    if args.echo:
        reply = anyio.run(call_echo, args.url, args.echo, transcript)
    elif args.url:
        results = anyio.run(run_http, args.url, transcript)
    else:
        results = anyio.run(run_stdio, server_params(args.db), transcript)

    for wire in transcript:
        print(f"\n{describe(wire)}")
        print(json.dumps(wire.message, indent=2, ensure_ascii=False))
    if args.echo:
        print(f"\nEcho replied: {reply}")
        return
    print(
        f"\nEvery primitive worked: {len(results.tool_names)} tools, "
        f"{len(results.pending)} pending task(s), resource and prompt read."
    )


if __name__ == "__main__":
    main()
