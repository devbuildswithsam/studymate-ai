"""/mcp in the FastAPI app: Streamable HTTP, stateless. SMA-41, SMA-61.

Every request passes through McpEndpoint first: it finds the user, stores it in the tool
context, and only then hands the request to the MCP server.
- AUTH_MODE=jwt (SMA-61): the owner of a valid personal access token sent as
  'Authorization: Bearer <token>'. Anything else: 401 before any tool runs.
- AUTH_MODE=local: the seeded user, and only callers on this computer.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.deps import LOOPBACK_HOSTS
from app.config import app_settings
from app.db.seed import find_local_user
from app.db.session import _session_factory
from app.errors import error_response
from app.mcp_server.context import ToolContext, acting_as
from app.mcp_server.server import mcp_server
from app.services.access_tokens import owner_of
from app.services.llm.embeddings import build_embedding_provider
from app.services.llm.registry import get_registry

BEARER_NEEDED = (
    "/mcp needs a personal access token: make one on the Settings page and send it as "
    "'Authorization: Bearer <token>'."
)


def bearer_token(scope: Scope) -> str | None:
    """The token from 'Authorization: Bearer <token>', or None for anything else."""
    header = Headers(scope=scope).get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


class McpEndpoint:
    """The ASGI app behind the /mcp route."""

    def __init__(self) -> None:
        self.handler: ASGIApp | None = None  # set while the app runs (see run_mcp)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        settings = app_settings(scope)
        session_factory = _session_factory(settings.database_url)

        if settings.auth_mode == "jwt":
            # SMA-61: a personal access token, and nothing else. The session cookie is NOT
            # accepted: /mcp is for programs, and a cookie would make it a CSRF target.
            token = bearer_token(scope)
            with session_factory() as db:
                user = owner_of(db, token) if token else None
            if user is None:
                response = error_response(401, BEARER_NEEDED)
                response.headers["WWW-Authenticate"] = 'Bearer realm="StudyMate"'
                await response(scope, receive, send)
                return
        else:
            client = scope.get("client")
            if (client[0] if client else None) not in LOOPBACK_HOSTS:
                response = error_response(
                    403, "AUTH_MODE=local only accepts requests from this computer."
                )
                await response(scope, receive, send)
                return
            with session_factory() as db:
                user = find_local_user(db)
            if user is None:
                response = error_response(
                    500, "The local user is missing. Run: python -m scripts.seed"
                )
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
