"""GET /api/progress?today=YYYY-MM-DD: the Progress page's numbers. SMA-65.

Read-only. `today` is the browser's date, so "overdue" follows the student's own calendar
(the server runs in UTC). Every number counts only this user's own data.
"""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.db.session import get_db
from app.models.common import as_utc
from app.repositories import progress as repo

router = APIRouter(prefix="/api/progress", tags=["progress"])


class QuizPoint(BaseModel):
    created_at: datetime
    quiz_title: str
    score: int
    total: int


class QuizNumbers(BaseModel):
    attempts: int
    average_percent: int | None  # None: no attempt yet
    history: list[QuizPoint]  # the most recent attempts, oldest first (for the chart)


class FlashcardNumbers(BaseModel):
    decks: int
    cards_reviewed: int  # cards marked at least once
    cards_known: int  # cards whose latest mark is "knew it"
    reviews: int  # every mark ever made


class TaskNumbers(BaseModel):
    done_last_7_days: int
    open: int
    overdue: int


class DocumentNumbers(BaseModel):
    ready: int
    studied: int  # used in a study chat, a quiz or a flashcard deck


class Progress(BaseModel):
    quizzes: QuizNumbers
    flashcards: FlashcardNumbers
    tasks: TaskNumbers
    documents: DocumentNumbers


@router.get("", response_model=Progress)
def get_progress(
    today: date,
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Progress:
    attempts = repo.quiz_attempts(db, user_id)
    # Each attempt counts equally, whatever its length.
    percents = [100 * score / total for _, _, score, total in attempts if total]
    reviews, latest = repo.card_marks(db, user_id)
    return Progress(
        quizzes=QuizNumbers(
            attempts=len(attempts),
            average_percent=round(sum(percents) / len(percents)) if percents else None,
            history=[
                QuizPoint(created_at=as_utc(when), quiz_title=title, score=score, total=total)
                for when, title, score, total in attempts[-repo.HISTORY_LENGTH :]
            ],
        ),
        flashcards=FlashcardNumbers(
            decks=repo.deck_count(db, user_id),
            cards_reviewed=len(latest),
            cards_known=sum(latest.values()),
            reviews=reviews,
        ),
        tasks=TaskNumbers(**repo.task_numbers(db, user_id, today)),
        documents=DocumentNumbers(**repo.document_numbers(db, user_id)),
    )
