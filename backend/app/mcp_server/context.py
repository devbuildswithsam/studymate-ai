"""Who the MCP tools act for: a request-scoped context, set ONLY by the backend. SMA-41.

The AI writes tool arguments, so a user_id there could name anyone. Instead, the backend
(the /mcp endpoint now, the chat's agent loop in SMA-42) resolves the signed-in user and
stores it here before any tool runs; every tool reads it from here. A ContextVar is
per-request: two requests at the same time never see each other's user.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy.orm import Session

if TYPE_CHECKING:  # for type hints only: avoids importing the LLM code here
    from app.services.llm.embeddings import EmbeddingProvider


@dataclass(frozen=True)
class ToolContext:
    user_id: str
    session_factory: Callable[[], Session]  # opens a session on the app's database
    # SMA-48: builds the embedding provider for search_documents (the question must be
    # embedded with the same model as the chunks). None = search isn't available here.
    make_embedder: "Callable[[], EmbeddingProvider] | None" = None


_current: ContextVar[ToolContext | None] = ContextVar("mcp_tool_context", default=None)


@contextmanager
def acting_as(context: ToolContext) -> Iterator[None]:
    """Run the code inside (tool calls) for this user; restored afterwards."""
    token = _current.set(context)
    try:
        yield
    finally:
        _current.reset(token)


def current_context() -> ToolContext:
    """The signed-in user's context. Fails closed: no context, no tool."""
    context = _current.get()
    if context is None:
        raise ToolError("No signed-in user: tools only run inside a StudyMate request.")
    return context


@contextmanager
def tool_db() -> Iterator[tuple[Session, str]]:
    """A database session and the current user's id, for one tool call."""
    context = current_context()
    with context.session_factory() as db:
        yield db, context.user_id
