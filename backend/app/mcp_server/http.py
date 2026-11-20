"""/mcp in the FastAPI app: Streamable HTTP, stateless, local mode only. SMA-41.

Every request passes through McpEndpoint first: it finds the user the way the rest of
the app does (local mode: the seeded user, and only callers on this computer), stores it
in the tool context, and only then hands the request to the MCP server.

v1.1 (real auth) replaces the local-user part with a bearer-token check (guide 7.2).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.deps import LOOPBACK_HOSTS
from app.config import app_settings
from app.db.seed import find_local_user
from app.db.session import _session_factory
from app.errors import error_response
from app.mcp_server.context import ToolContext, acting_as
from app.mcp_server.server import mcp_server
from app.services.llm.embeddings import build_embedding_provider
from app.services.llm.registry import get_registry


class McpEndpoint:
    """The ASGI app behind the /mcp route."""

    def __init__(self) -> None:
        self.handler: ASGIApp | None = None  # set while the app runs (see run_mcp)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        settings = app_settings(scope)
        if settings.auth_mode != "local":
            # Real accounts are on, but personal access tokens (SMA-61) aren't built yet:
            # closed, never open. The session cookie isn't accepted here on purpose (/mcp
            # is for other programs, and a cookie would make it a CSRF target).
            response = error_response(
                401, "/mcp needs a personal access token, which isn't available yet."
            )
            await response(scope, receive, send)
            return

        client = scope.get("client")
        if (client[0] if client else None) not in LOOPBACK_HOSTS:
            response = error_response(
                403, "AUTH_MODE=local only accepts requests from this computer."
            )
            await response(scope, receive, send)
            return

        session_factory = _session_factory(settings.database_url)
        with session_factory() as db:
            user = find_local_user(db)
        if user is None:
            response = error_response(500, "The local user is missing. Run: python -m scripts.seed")
            await response(scope, receive, send)
            return

        if self.handler is None:
            await error_response(503, "The MCP server is not running.")(scope, receive, send)
            return
        # Every tool called during this request acts for this user, and only this user.
        context = ToolContext(
            user_id=user.id,
            session_factory=session_factory,
            # SMA-48: search_documents embeds the question with the app's embedding model.
            make_embedder=lambda: build_embedding_provider(get_registry(), settings),
        )
        with acting_as(context):
            await self.handler(scope, receive, send)


@asynccontextmanager
async def run_mcp(endpoint: McpEndpoint) -> AsyncIterator[None]:
    """Run the MCP HTTP handler while the app runs (call it from the app's lifespan).

    A session manager can only be started once, so every start builds a fresh one (tests
    start the app many times).
    """
    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,  # every POST stands alone: nothing kept between requests
        json_response=True,  # plain JSON answers, no server-sent-event streams
    )
    endpoint.handler = mcp_app.routes[0].app  # its single /mcp route
    try:
        async with mcp_app.router.lifespan_context(mcp_app):  # runs the session manager
            yield
    finally:
        endpoint.handler = None
