"""The AI's writes: confirmation cards and Undo (guide 7.2 write-action policy). SMA-43.

POST /api/actions/{id}/confirm   a pending card: run the tool now, for me
POST /api/actions/{id}/cancel    a pending card: don't run it
POST /api/actions/{id}/undo      a create that ran: remove what it made

Only a click here can run a held action: the AI can't confirm its own cards (no tool does).
The user comes only from get_current_user_id. Another user's action answers 404.
"""

from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.config import Settings, get_settings
from app.db.session import _session_factory, get_db
from app.mcp_server.context import ToolContext
from app.models import AgentAction
from app.models.common import utcnow
from app.services import actions as service

router = APIRouter(prefix="/api/actions", tags=["actions"])

CurrentUserId = Annotated[str, Depends(get_current_user_id)]
Db = Annotated[Session, Depends(get_db)]


class ActionOut(BaseModel):
    """One card or Undo button under an AI answer."""

    model_config = {"from_attributes": True}

    id: str
    tool: str  # e.g. "complete_task"
    kind: str  # "create" or "change"
    status: str  # pending / done / cancelled / failed / undone
    summary: str  # "Mark 'Revise ch.3' as done"
    error: str | None  # why a confirmed action failed


@router.post("/{action_id}/confirm", response_model=ActionOut)
def confirm(
    action_id: str,
    user_id: CurrentUserId,
    db: Db,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentAction:
    action = my_action(db, user_id, action_id, status="pending")
    context = ToolContext(user_id, _session_factory(settings.database_url))
    # This route runs in a worker thread: from_thread.run runs the MCP call on the app's
    # event loop (as in the chat route, SMA-42).
    result, error = anyio.from_thread.run(
        service.run_confirmed, context, action.tool, action.arguments
    )
    service.finish_confirmed(action, result, error)
    db.commit()
    return action


@router.post("/{action_id}/cancel", response_model=ActionOut)
def cancel(action_id: str, user_id: CurrentUserId, db: Db) -> AgentAction:
    action = my_action(db, user_id, action_id, status="pending")
    action.status = "cancelled"
    action.resolved_at = utcnow()
    db.commit()
    return action


@router.post("/{action_id}/undo", response_model=ActionOut)
def undo(action_id: str, user_id: CurrentUserId, db: Db) -> AgentAction:
    action = my_action(db, user_id, action_id, status="done")
    if action.kind != "create":
        # Undoing a change would need the old values; the card asked first instead.
        raise HTTPException(409, "Only something the AI created can be undone.")
    service.undo(db, user_id, action)
    db.commit()
    return action


def my_action(db: Session, user_id: str, action_id: str, *, status: str) -> AgentAction:
    """The user's action in the given status: 404 if it isn't theirs, 409 if already used."""
    action = db.scalar(
        select(AgentAction).where(AgentAction.id == action_id, AgentAction.user_id == user_id)
    )
    if action is None:
        raise HTTPException(404, "Action not found")
    if action.status != status:
        raise HTTPException(409, f"This action is already {action.status}.")
    return action
