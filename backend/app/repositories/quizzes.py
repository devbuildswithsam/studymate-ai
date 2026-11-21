"""Queries for quizzes and their attempts. SMA-63. Every lookup takes user_id."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Document, Quiz, QuizAttempt
from app.services.quiz import QuizDraft


def document_pieces(db: Session, document: Document) -> list[tuple[int | None, str]]:
    """The document's text in reading order, as (page, text) chunks."""
    rows = db.execute(
        select(Chunk.page, Chunk.text)
        .where(Chunk.document_id == document.id)
        .order_by(Chunk.chunk_index)
    )
    return [(page, text) for page, text in rows]


def create_quiz(
    db: Session, user_id: str, document: Document, draft: QuizDraft, model: str | None
) -> Quiz:
    quiz = Quiz(
        user_id=user_id,
        document_id=document.id,
        document_name=document.filename,
        title=draft.title,
        questions=draft.questions,
        model=model,
    )
    db.add(quiz)
    db.flush()
    return quiz


def list_quizzes(db: Session, user_id: str) -> list[Quiz]:
    query = select(Quiz).where(Quiz.user_id == user_id).order_by(Quiz.created_at.desc())
    return list(db.scalars(query))


def get_quiz(db: Session, user_id: str, quiz_id: str) -> Quiz | None:
    return db.scalar(select(Quiz).where(Quiz.id == quiz_id, Quiz.user_id == user_id))


def attempts_of(db: Session, user_id: str, quiz_ids: list[str]) -> list[QuizAttempt]:
    """The user's attempts on these quizzes, oldest first."""
    query = (
        select(QuizAttempt)
        .where(QuizAttempt.user_id == user_id, QuizAttempt.quiz_id.in_(quiz_ids))
        .order_by(QuizAttempt.created_at)
    )
    return list(db.scalars(query))


def add_attempt(
    db: Session, user_id: str, quiz: Quiz, answers: list[int | None], score: int
) -> QuizAttempt:
    attempt = QuizAttempt(
        quiz_id=quiz.id, user_id=user_id, answers=answers, score=score, total=len(quiz.questions)
    )
    db.add(attempt)
    db.flush()
    return attempt
