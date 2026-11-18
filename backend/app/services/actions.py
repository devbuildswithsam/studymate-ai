"""The AI's writes after the policy has decided (guide 7.2). SMA-43.

record_actions: after a chat answer, one AgentAction per create or change the AI asked for
  (held -> a pending card; a create that ran -> "done", so it can be undone).
run_confirmed: the student clicked Confirm, so the tool runs now (through MCP, for them).
undo: remove what a create made.
"""

import json
from typing import Any

from mcp import Client
from mcp.shared.exceptions import MCPError
from sqlalchemy.orm import Session

from app.mcp_server.context import ToolContext, acting_as
from app.mcp_server.server import TOOL_KINDS, mcp_server
from app.models import AgentAction, Message
from app.models.common import utcnow
from app.repositories import notes as notes_repo
from app.repositories import tasks as tasks_repo
from app.services.agent import ToolStep


def record_actions(
    db: Session, user_id: str, answer: Message, steps: list[ToolStep]
) -> list[AgentAction]:
    actions = []
    for step in steps:
        kind = TOOL_KINDS.get(step.name)
        if kind not in ("create", "change") or (step.is_error and not step.held):
            continue  # reads change nothing; a failed call changed nothing
        arguments = json.loads(step.arguments or "{}")
        action = AgentAction(
            user_id=user_id,
            message_id=answer.id,
            position=len(actions) + 1,
            tool=step.name,
            kind=kind,
            arguments=arguments,
            summary=describe(db, user_id, step.name, arguments),
            status="pending" if step.held else "done",
            # A create that ran: remember what it made, for Undo.
            target_id=None if step.held else json.loads(step.result).get("id"),
        )
        db.add(action)
        actions.append(action)
    db.flush()
    return actions


def describe(db: Session, user_id: str, tool: str, arguments: dict[str, Any]) -> str:
    """What the card says, in words: "Mark 'Revise ch.3' as done"."""
    if tool == "create_task":
        due = f" (due {arguments['due_date']})" if arguments.get("due_date") else ""
        return f"Add task '{arguments.get('title', '')}'{due}"
    if tool == "save_note":
        return f"Save note '{arguments.get('title', '')}'"
    # Changes name the task by its title (looked up for THIS user only), not by its id.
    task = tasks_repo.get_task(db, user_id, str(arguments.get("task_id", "")))
    name = f"'{task.title}'" if task else f"task {arguments.get('task_id')} (not found)"
    if tool == "complete_task":
        return f"Mark {name} as done"
    changes = ", ".join(f"{k} → {v}" for k, v in arguments.items() if k != "task_id")
    return f"Change {name}: {changes}"[:300]


async def run_confirmed(
    context: ToolContext, tool: str, arguments: dict[str, Any]
) -> tuple[dict | None, str | None]:
    """Run a confirmed action's tool for the student. Returns (result, None) or (None, why)."""
    with acting_as(context):
        async with Client(mcp_server) as session:
            try:
                result = await session.call_tool(tool, arguments)
            except MCPError as e:
                return None, e.error.message
    if result.is_error:
        return None, "\n".join(p.text for p in result.content if getattr(p, "text", None))
    return result.structured_content, None


def finish_confirmed(action: AgentAction, result: dict | None, error: str | None) -> None:
    action.status = "failed" if error else "done"
    action.error = error
    if result and action.kind == "create":
        action.target_id = result.get("id")  # now it can be undone too
    action.resolved_at = utcnow()


def undo(db: Session, user_id: str, action: AgentAction) -> None:
    """Remove what a create made. Already deleted by the student? Then there's nothing to do."""
    if action.tool == "create_task":
        tasks_repo.delete_task(db, user_id, action.target_id)
    elif action.tool == "save_note":
        notes_repo.delete_note(db, user_id, action.target_id)
    action.status = "undone"
    action.resolved_at = utcnow()
