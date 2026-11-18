"""The FastAPI app. Run from backend/:  uvicorn app.main:app --reload   SMA-20.

`app` is an ASGI application: uvicorn (the server) calls it for every request.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.routing import Route

from app.api import conversations, health, models, notes, tasks
from app.config import APP_VERSION, get_settings
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

# CORS: the browser only lets our React app (FRONTEND_ORIGIN) read API responses.
# One explicit origin, never "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(models.router)
app.include_router(conversations.router)
app.include_router(notes.router)
app.include_router(tasks.router)
# MCP (guide 7.2): StudyMate's tools for AI clients. Local mode: this computer only.
app.router.routes.append(Route("/mcp", endpoint=mcp_endpoint))
