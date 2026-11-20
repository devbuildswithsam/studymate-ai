"""The FastAPI app. Run from backend/:  uvicorn app.main:app --reload   SMA-20.

`app` is an ASGI application: uvicorn (the server) calls it for every request.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.routing import Route

from app.api import actions, auth, conversations, documents, health, models, notes, tasks
from app.config import APP_VERSION, get_settings
from app.csrf import CSRF_HEADER, CsrfMiddleware
from app.errors import register_error_handlers
from app.mcp_server.http import McpEndpoint, run_mcp
from app.services.llm.registry import get_registry

settings = get_settings()
get_registry()  # validate models.yaml now: a mistake stops startup with a clear error

mcp_endpoint = McpEndpoint()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Runs while the app runs: here, the MCP server's HTTP handler (SMA-41)."""
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
)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(auth.router)  # SMA-57
app.include_router(models.router)
app.include_router(conversations.router)
app.include_router(notes.router)
app.include_router(tasks.router)
app.include_router(actions.router)  # SMA-43
app.include_router(documents.router)  # SMA-44
# MCP (guide 7.2): StudyMate's tools for AI clients. Local mode: this computer only.
app.router.routes.append(Route("/mcp", endpoint=mcp_endpoint))
