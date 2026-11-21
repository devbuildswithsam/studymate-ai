"""quizzes and quiz_attempts (guide Stage 5 "Quizzes"). SMA-63.

A quiz keeps its own copy of the questions (with the right answers), so it still works
after its document is deleted: the link is just cleared. Every attempt is saved, for the
Progress page (SMA-65).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import new_id, utcnow


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # SET NULL: deleting the document keeps the quiz (it has its own copy of the questions).
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    document_name: Mapped[str] = mapped_column(String(255))  # shown even after deletion
    title: Mapped[str] = mapped_column(String(120))
    # [{"question", "options": [4], "answer": 0-3, "explanation", "page"}]. The answers
    # never leave the server before an attempt is submitted.
    questions: Mapped[list[Any]] = mapped_column(JSON)
    model: Mapped[str | None] = mapped_column(String(100))  # which AI wrote it
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    quiz_id: Mapped[str] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    answers: Mapped[list[Any]] = mapped_column(JSON)  # the chosen option per question
    score: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
