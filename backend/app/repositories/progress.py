"""The numbers behind the Progress page. SMA-65.

Read-only, and EVERY query is filtered by user_id: someone else's quizzes, cards, tasks
or documents never count.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import CardReview, Conversation, Deck, Document, Quiz, QuizAttempt, Task
from app.models.common import utcnow
from app.models.document import conversation_documents

HISTORY_LENGTH = 20  # quiz attempts shown on the chart, most recent


def quiz_attempts(db: Session, user_id: str) -> list[tuple[datetime, str, int, int]]:
    """(when, quiz title, score, total) for every attempt, oldest first."""
    rows = db.execute(
        select(QuizAttempt.created_at, Quiz.title, QuizAttempt.score, QuizAttempt.total)
        .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
        .where(QuizAttempt.user_id == user_id, Quiz.user_id == user_id)
        .order_by(QuizAttempt.created_at)
    )
    return [tuple(row) for row in rows]


def card_marks(db: Session, user_id: str) -> tuple[int, dict[tuple[str, int], bool]]:
    """(number of reviews, the latest mark per card). The latest mark is the one that counts."""
    reviews = db.scalars(
        select(CardReview).where(CardReview.user_id == user_id).order_by(CardReview.created_at)
    ).all()
    latest = {(r.deck_id, r.card_index): r.knew for r in reviews}  # later ones overwrite
    return len(reviews), latest


def deck_count(db: Session, user_id: str) -> int:
    return db.scalar(select(func.count()).select_from(Deck).where(Deck.user_id == user_id)) or 0


def task_numbers(db: Session, user_id: str, today: date) -> dict[str, int]:
    def count(*conditions) -> int:
        query = select(func.count()).select_from(Task).where(Task.user_id == user_id, *conditions)
        return db.scalar(query) or 0

    week_ago = utcnow() - timedelta(days=7)
    return {
        "done_last_7_days": count(Task.status == "done", Task.completed_at >= week_ago),
        "open": count(Task.status != "done"),
        # "today" comes from the browser: a task due today in India isn't late at 23:00 UTC.
        "overdue": count(Task.status != "done", Task.due_date < today),
    }


def document_numbers(db: Session, user_id: str) -> dict[str, int]:
    """Ready documents, and how many were STUDIED: used in a study chat, a quiz or a deck."""
    ready = select(Document.id).where(Document.user_id == user_id, Document.status == "ready")
    in_chats = (
        select(conversation_documents.c.document_id)
        .join(Conversation, Conversation.id == conversation_documents.c.conversation_id)
        .where(Conversation.user_id == user_id)
    )
    in_quizzes = select(Quiz.document_id).where(Quiz.user_id == user_id)
    in_decks = select(Deck.document_id).where(Deck.user_id == user_id)
    studied = ready.where(
        or_(Document.id.in_(in_chats), Document.id.in_(in_quizzes), Document.id.in_(in_decks))
    )
    return {
        "ready": db.scalar(select(func.count()).select_from(ready.subquery())) or 0,
        "studied": db.scalar(select(func.count()).select_from(studied.subquery())) or 0,
    }
