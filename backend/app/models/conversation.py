"""conversations and messages (guide 7.1 + the extra columns from 7.5). SMA-28.

conversations.mode (general / study) was added in SMA-33's migration exercise.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import allowed, new_id, utcnow

if TYPE_CHECKING:  # for type hints only; avoids a circular import at runtime
    from app.models.agent_action import AgentAction
    from app.models.document import Document
    from app.models.user import User

MESSAGE_ROLES = ("user", "assistant", "tool")
MESSAGE_MODES = ("general", "grounded", "tool")  # the badge on an answer
CONVERSATION_MODES = ("general", "study")  # study = chat about your documents (Stage 4)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (CheckConstraint(allowed("mode", CONVERSATION_MODES), name="mode"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # ON DELETE CASCADE: deleting a user deletes their conversations, in the database itself.
    # index: "this user's conversations" is the most common query.
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    # server_default: the DATABASE fills it in. That's what gives existing rows a value
    # when the column is added (SMA-33); default= alone only works for inserts from Python.
    mode: Mapped[str] = mapped_column(String(20), default="general", server_default="general")
    provider: Mapped[str | None] = mapped_column(String(50))  # the model chosen for this chat
    model: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.position",
        # Never load messages with a hidden query (one per conversation = N+1 queries):
        # ask for them up front with selectinload, or get an error. SMA-30.
        lazy="raise",
    )
    # SMA-44: the documents a study chat may search (many-to-many, guide 7.1).
    # passive_deletes: the database's CASCADE removes the links when either side goes.
    documents: Mapped[list["Document"]] = relationship(
        secondary="conversation_documents", passive_deletes=True, lazy="raise"
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        # The database refuses anything else, even if a bug in Python tries.
        CheckConstraint(allowed("role", MESSAGE_ROLES), name="role"),
        CheckConstraint(allowed("mode", MESSAGE_MODES), name="mode"),
        # One message per slot. Its index also serves "the last 10 messages" (SMA-30).
        UniqueConstraint("conversation_id", "position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    # 1, 2, 3... within the conversation. The order of messages: created_at can't be
    # trusted for that (Windows' clock gives many rows the very same time). SMA-30.
    position: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    # Answer details for the badges (empty on the user's own messages).
    provider: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    mode: Mapped[str | None] = mapped_column(String(20))
    fallback_used: Mapped[bool] = mapped_column(default=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    citations: Mapped[list | None] = mapped_column(JSON)  # Stage 4: [{document, page, ...}]
    tool_calls: Mapped[list | None] = mapped_column(JSON)  # the MCP tools used (SMA-42)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    # SMA-43: the AI's writes for this answer (cards and Undo). lazy="raise": load them
    # with selectinload, never one hidden query per message.
    actions: Mapped[list["AgentAction"]] = relationship(
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentAction.position",
        lazy="raise",
    )
