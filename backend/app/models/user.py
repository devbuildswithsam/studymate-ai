"""users: one row per person. Everything else belongs to a user (guide 7.1). SMA-28."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import new_id, utcnow

if TYPE_CHECKING:  # for type hints only; avoids a circular import at runtime
    from app.models.conversation import Conversation
    from app.models.note import Note


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str | None] = mapped_column(String(200))
    # Empty in single-user local mode; real logins arrive in Stage 5.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # passive_deletes: let the database's ON DELETE CASCADE do the deleting.
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    notes: Mapped[list["Note"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
