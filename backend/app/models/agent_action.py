"""agent_actions: writes the AI made or wants to make (guide 7.2 write-action policy). SMA-43.

One row per create or change the AI asked for in a chat answer:
- pending   -> held for the student: shown as a confirmation card (Confirm / Cancel)
- done      -> ran (a create the student asked for, or a confirmed card)
- cancelled -> the student said no;  failed -> confirmed, but the tool refused
- undone    -> a create removed again with the Undo button
Reads make no rows: they change nothing.
"""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import allowed, new_id, utcnow

ACTION_KINDS = ("create", "change")  # TOOL_KINDS minus "read"
ACTION_STATUSES = ("pending", "done", "cancelled", "failed", "undone")


class AgentAction(Base):
    __tablename__ = "agent_actions"
    __table_args__ = (
        CheckConstraint(allowed("kind", ACTION_KINDS), name="kind"),
        CheckConstraint(allowed("status", ACTION_STATUSES), name="status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # The owner: every lookup filters on it (the isolation rule).
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # The answer it belongs to: the card shows under that answer. Deleting the chat
    # deletes its cards (CASCADE).
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)  # order under the answer (not created_at)
    tool: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(10))
    arguments: Mapped[dict] = mapped_column(JSON)  # exactly what the AI asked for
    summary: Mapped[str] = mapped_column(String(300))  # "Mark 'Revise ch.3' as done"
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    target_id: Mapped[str | None] = mapped_column(String(36))  # the created task/note, for Undo
    error: Mapped[str | None] = mapped_column(Text)  # why a confirmed action failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
