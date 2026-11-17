"""One-tool MCP echo server for Vercel (SMA-38). No data, no secrets, no login.

A transport test: does MCP over Streamable HTTP work on Vercel, from our own client and
from Claude Desktop? Vercel finds `app` in main.py (like experiments/vercel-poc).

Run locally (from mcp_lab/, venv active):
    .venv\\Scripts\\python -m uvicorn vercel_echo.main:app --port 8766
"""

import os
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

server = MCPServer(
    "StudyMate echo",
    instructions="Sends text back unchanged. A transport test: it stores nothing.",
)


@server.tool()
def echo(
    text: Annotated[str, Field(min_length=1, max_length=500, description="Text to send back")],
) -> str:
    """Send the text back unchanged."""
    return text


def allowed_hosts() -> list[str]:
    """Only our own addresses may be used in the Host header (DNS-rebinding protection).

    On Vercel these environment variables hold this deployment's hostnames. Without them
    (running locally) only localhost is allowed. Any other Host gets 421.
    """
    names = ("VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_URL", "VERCEL_BRANCH_URL")
    hosts = [os.environ[name] for name in names if os.environ.get(name)]
    return hosts or ["127.0.0.1:*", "localhost:*"]


app = server.streamable_http_app(
    # stateless_http: every POST stands alone, nothing kept between requests (serverless).
    stateless_http=True,
    # json_response: answer each POST with plain JSON instead of a server-sent-event stream.
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=allowed_hosts()
    ),
)
