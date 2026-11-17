"""Tasks (wireframe 6.6: To do / Doing / Done). SMA-40.

GET    /api/tasks?status=   my tasks, soonest due first (optionally one column)
POST   /api/tasks           create (always created_by "user": only MCP tools set "ai")
PATCH  /api/tasks/{id}      edit or move between columns (send only what changes)
DELETE /api/tasks/{id}      delete (a UI button; the AI's tools never delete)

The user comes only from get_current_user_id. Another user's task answers 404.
"""

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, StringConstraints, model_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.db.session import get_db
from app.models import Task
from app.repositories import tasks as repo

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

CurrentUserId = Annotated[str, Depends(get_current_user_id)]
Db = Annotated[Session, Depends(get_db)]

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(max_length=2000)]
Priority = Literal["low", "medium", "high"]
Status = Literal["todo", "doing", "done"]


class TaskCreate(BaseModel):
    # Unknown fields (like created_by) are ignored: the AI marker can't be faked.
    title: Title
    description: Description | None = None
    due_date: date | None = None
    priority: Priority = "medium"
    status: Status = "todo"


class TaskUpdate(BaseModel):
    """Only the fields you send change. null clears description or due_date."""

    title: Title | None = None
    description: Description | None = None
    due_date: date | None = None
    priority: Priority | None = None
    status: Status | None = None

    @model_validator(mode="after")
    def required_fields_cannot_be_cleared(self) -> "TaskUpdate":
        for field in ("title", "priority", "status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} can't be empty")
        return self

    def changes(self) -> dict:
        """The fields that were actually sent (left out = unchanged)."""
        return {field: getattr(self, field) for field in self.model_fields_set}


class TaskOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    title: str
    description: str | None
    due_date: date | None
    priority: Priority
    status: Status
    document_id: str | None
    created_by: Literal["user", "ai"]  # "ai" shows the AI marker on the board
    created_at: datetime
    completed_at: datetime | None


@router.get("", response_model=list[TaskOut])
def list_tasks(
    user_id: CurrentUserId, db: Db, status: Annotated[Status | None, Query()] = None
) -> list[Task]:
    return repo.list_tasks(db, user_id, status)


@router.post("", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, user_id: CurrentUserId, db: Db) -> Task:
    task = repo.create_task(db, user_id, **body.model_dump(), created_by="user")
    db.commit()
    return task


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: str, body: TaskUpdate, user_id: CurrentUserId, db: Db) -> Task:
    task = repo.get_task(db, user_id, task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    repo.update_task(db, task, body.changes())
    db.commit()
    return task


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str, user_id: CurrentUserId, db: Db) -> Response:
    if not repo.delete_task(db, user_id, task_id):
        raise HTTPException(404, "Task not found")
    db.commit()
    return Response(status_code=204)
