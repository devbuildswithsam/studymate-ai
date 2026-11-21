"""decks and card_reviews: flashcards and how reviewing them went. SMA-64.

A deck keeps its own copy of the cards, so it still works after its source (a document,
or the chat answer it was made from) is deleted: the link is just cleared. Every
"knew it / didn't" is saved, for the Progress page (SMA-65).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import allowed, new_id, utcnow

DECK_SOURCES = ("document", "answer")


class Deck(Base):
    __tablename__ = "decks"
    __table_args__ = (CheckConstraint(allowed("source_type", DECK_SOURCES), name="source_type"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    source_type: Mapped[str] = mapped_column(String(10))  # "document" or "answer"
    source_name: Mapped[str] = mapped_column(String(255))  # file name or chat title, shown
    # SET NULL: deleting the source keeps the deck (it has its own copy of the cards).
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    cards: Mapped[list[Any]] = mapped_column(JSON)  # [{"front", "back", "page"}]
    model: Mapped[str | None] = mapped_column(String(100))  # which AI wrote it
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CardReview(Base):
    __tablename__ = "card_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    deck_id: Mapped[str] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    card_index: Mapped[int] = mapped_column(Integer)  # which card of the deck (0, 1, 2...)
    knew: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
