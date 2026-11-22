"""The FastAPI app. Run from backend/:  uvicorn app.main:app --reload   SMA-20.

`app` is an ASGI application: uvicorn (the server) calls it for every request.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.routing import Route

from app.api import (
    actions,
    admin,
    auth,
    conversations,
    decks,
    documents,
    health,
    models,
    notes,
    progress,
    quizzes,
    tasks,
    tokens,
)
from app.config import APP_VERSION, get_settings
from app.csrf import CSRF_HEADER, CsrfMiddleware
from app.db.migrations import check_database_is_current
from app.errors import register_error_handlers
from app.logs import HEADER as REQUEST_ID_HEADER
from app.logs import RequestIdMiddleware, configure_logging
from app.mcp_server.http import McpEndpoint, run_mcp
from app.services.llm.registry import get_registry

settings = get_settings()
get_registry()  # validate models.yaml now: a mistake stops startup with a clear error

mcp_endpoint = McpEndpoint()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Runs while the app runs: here, the MCP server's HTTP handler (SMA-41)."""
    # SMA-61: refuse to start on a database that is behind the code's migrations, with the
    # command that fixes it, instead of failing later on some page. The settings come the
    # same way routes get them, so tests check their own temporary databases.
    current_settings = app.dependency_overrides.get(get_settings, get_settings)()
    # SMA-68: JSON log lines from here on. Not in tests: they capture logs their own way.
    if current_settings.env != "test":
        configure_logging()
    check_database_is_current(current_settings.database_url)
    async with run_mcp(mcp_endpoint):
        yield


app = FastAPI(title="StudyMate AI", version=APP_VERSION, lifespan=lifespan)

# CSRF (SMA-58): other websites can't make your browser change anything here. Added
# before CORS, so CORS wraps it and even a 403 from here carries the CORS headers.
app.add_middleware(CsrfMiddleware)

# CORS: the browser only lets our React app (FRONTEND_ORIGIN) read API responses.
# One explicit origin, never "*". CORS is NOT CSRF protection: it stops other sites
# reading answers, not sending requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", CSRF_HEADER],
    expose_headers=[REQUEST_ID_HEADER],  # SMA-68: the page may read it, to show in errors
)

# SMA-68: added LAST, so it is the outermost layer: every response gets a request id,
# even a 403 from the CSRF check, and the access log line times the whole request.
app.add_middleware(RequestIdMiddleware)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(auth.router)  # SMA-57
app.include_router(models.router)
app.include_router(conversations.router)
app.include_router(notes.router)
app.include_router(tasks.router)
app.include_router(actions.router)  # SMA-43
app.include_router(documents.router)  # SMA-44
app.include_router(tokens.router)  # SMA-61
app.include_router(quizzes.router)  # SMA-63
app.include_router(decks.router)  # SMA-64
app.include_router(progress.router)  # SMA-65
app.include_router(admin.router)  # SMA-68
# MCP (guide 7.2): StudyMate's tools for AI clients. Local mode: this computer only.
app.router.routes.append(Route("/mcp", endpoint=mcp_endpoint))
