"""llm_calls: one row per call to an AI model, for usage, cost and failure monitoring.

Guide 7.1 ("supporting tables"). Written from Stage 2 on; read by the admin usage view later.
SMA-28.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import allowed, new_id, utcnow

if TYPE_CHECKING:  # for type hints only; avoids a circular import at runtime
    from app.models.conversation import Conversation
    from app.models.user import User

CALL_STATUSES = ("ok", "error")


class LLMCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (CheckConstraint(allowed("status", CALL_STATUSES), name="status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # SET NULL: deleting a conversation keeps its usage numbers.
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    error_type: Mapped[str | None] = mapped_column(String(50))  # e.g. rate_limited, timeout
    fallback_used: Mapped[bool] = mapped_column(default=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    time_to_first_token_ms: Mapped[int | None] = mapped_column(Integer)  # streaming, v1.1
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship()
    conversation: Mapped["Conversation | None"] = relationship()
