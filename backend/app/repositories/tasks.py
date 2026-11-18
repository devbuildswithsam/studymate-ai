"""Tasks: the user's study tasks. SMA-40.

Every lookup takes user_id. The same functions will serve the AI's MCP tools (SMA-41), so
rules like "moving to done records completed_at" live here, not in the endpoint.
"""

from datetime import date
from typing import Any

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.models import Task
from app.models.common import utcnow

# Soonest due first (no date last), then high > medium > low, then oldest first.
ORDER = (
    Task.due_date.is_(None),
    Task.due_date,
    case({"high": 0, "medium": 1}, value=Task.priority, else_=2),
    Task.created_at,
)


def list_tasks(
    db: Session,
    user_id: str,
    status: str | None = None,
    due_before: date | None = None,  # SMA-41: list_tasks tool filter
    limit: int | None = None,
) -> list[Task]:
    query = select(Task).where(Task.user_id == user_id)
    if status is not None:
        query = query.where(Task.status == status)
    if due_before is not None:
        query = query.where(Task.due_date < due_before)
    return list(db.scalars(query.order_by(*ORDER).limit(limit)))


def get_task(db: Session, user_id: str, task_id: str) -> Task | None:
    return db.scalar(select(Task).where(Task.id == task_id, Task.user_id == user_id))


def create_task(
    db: Session,
    user_id: str,
    *,
    title: str,
    description: str | None = None,
    due_date: date | None = None,
    priority: str = "medium",
    status: str = "todo",
    created_by: str = "user",  # the API always passes "user"; only MCP tools pass "ai"
) -> Task:
    task = Task(
        user_id=user_id,
        title=title,
        description=description,
        due_date=due_date,
        priority=priority,
        created_by=created_by,
    )
    set_status(task, status)
    db.add(task)
    db.flush()
    return task


def update_task(db: Session, task: Task, changes: dict[str, Any]) -> Task:
    """Apply changes to one of the user's tasks (the caller found it with get_task)."""
    for field in ("title", "description", "due_date", "priority"):
        if field in changes:
            setattr(task, field, changes[field])
    if "status" in changes:
        set_status(task, changes["status"])
    db.flush()
    return task


def set_status(task: Task, status: str) -> None:
    """Moving to done records when; moving out of done clears it; done -> done keeps it."""
    if status == "done" and task.status != "done":
        task.completed_at = utcnow()
    elif status != "done":
        task.completed_at = None
    task.status = status


def delete_task(db: Session, user_id: str, task_id: str) -> bool:
    task = get_task(db, user_id, task_id)
    if task is None:
        return False
    db.delete(task)
    db.flush()
    return True
