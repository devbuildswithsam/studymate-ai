"""tasks: study tasks, created by the user or by the AI (guide 7.1, wireframe 6.6). SMA-40."""

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import allowed, new_id, utcnow

if TYPE_CHECKING:  # for type hints only; avoids a circular import at runtime
    from app.models.user import User

TASK_STATUSES = ("todo", "doing", "done")  # the board's three columns
TASK_PRIORITIES = ("low", "medium", "high")
TASK_CREATORS = ("user", "ai")  # "ai" only ever set by the MCP tools (SMA-41)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(allowed("status", TASK_STATUSES), name="status"),
        CheckConstraint(allowed("priority", TASK_PRIORITIES), name="priority"),
        CheckConstraint(allowed("created_by", TASK_CREATORS), name="created_by"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    # server_default: the DATABASE fills these in (SMA-33 lesson), so every writer gets them.
    priority: Mapped[str] = mapped_column(String(10), default="medium", server_default="medium")
    status: Mapped[str] = mapped_column(String(10), default="todo", server_default="todo")
    # The document this task is about. documents arrive in Stage 4: the foreign key is
    # added then (a foreign key can't point to a table that doesn't exist yet).
    document_id: Mapped[str | None] = mapped_column(String(36))
    created_by: Mapped[str] = mapped_column(String(10), default="user", server_default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship()
