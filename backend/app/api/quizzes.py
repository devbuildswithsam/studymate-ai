"""Quizzes (guide Stage 5 "Quizzes"). SMA-63.

POST   /api/quizzes                 make one from a ready document: {"document_id", "questions": 5|10}
GET    /api/quizzes                 mine, newest first, with attempts and best / last score
GET    /api/quizzes/{id}            one quiz to take: questions and options, NO answers
POST   /api/quizzes/{id}/attempts   submit answers: scored here, then answers + explanations
DELETE /api/quizzes/{id}            delete it and its attempts

The right answers never leave the server before an attempt: the browser can't peek.
The user comes only from get_current_user_id. Another user's quiz answers 404.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.db.session import get_db
from app.models import Quiz
from app.models.common import as_utc
from app.repositories import conversations as calls_repo
from app.repositories import documents as documents_repo
from app.repositories import quizzes as repo
from app.services.llm.fallback import FallbackManager, get_fallback_manager
from app.services.llm.registry import ModelRegistry, get_registry
from app.services.quiz import QuizFailed, generate_quiz
from app.services.rate_limits import rate_limit

router = APIRouter(prefix="/api/quizzes", tags=["quizzes"])

CurrentUserId = Annotated[str, Depends(get_current_user_id)]
Db = Annotated[Session, Depends(get_db)]


class QuizCreate(BaseModel):
    document_id: str
    questions: Literal[5, 10] = 5


class QuestionOut(BaseModel):
    """A question as the student sees it before answering: no answer, no explanation."""

    question: str
    options: list[str]
    page: int | None


class QuizOut(BaseModel):
    id: str
    title: str
    document_id: str | None  # None once the document was deleted
    document_name: str
    created_at: datetime
    questions: list[QuestionOut]


class QuizSummary(BaseModel):
    id: str
    title: str
    document_id: str | None
    document_name: str
    created_at: datetime
    question_count: int
    attempts: int
    best_score: int | None  # None: not taken yet
    last_score: int | None


class AttemptIn(BaseModel):
    # One entry per question: the chosen option (0-3), or null for "skipped".
    answers: list[Annotated[int, Field(ge=0, le=3)] | None]


class ResultOut(BaseModel):
    chosen: int | None
    correct_answer: int
    is_correct: bool
    explanation: str
    page: int | None


class AttemptOut(BaseModel):
    id: str
    score: int
    total: int
    results: list[ResultOut]


def quiz_out(quiz: Quiz) -> QuizOut:
    return QuizOut(
        id=quiz.id,
        title=quiz.title,
        document_id=quiz.document_id,
        document_name=quiz.document_name,
        created_at=as_utc(quiz.created_at),
        questions=[
            QuestionOut(**{k: q[k] for k in ("question", "options", "page")})
            for q in quiz.questions
        ],
    )


def my_quiz(db: Session, user_id: str, quiz_id: str) -> Quiz:
    quiz = repo.get_quiz(db, user_id, quiz_id)
    if quiz is None:
        raise HTTPException(404, "Quiz not found")
    return quiz


@router.post(
    "",
    response_model=QuizOut,
    status_code=201,
    dependencies=[Depends(rate_limit("generate"))],  # SMA-67
)
def create_quiz(
    body: QuizCreate,
    user_id: CurrentUserId,
    db: Db,
    registry: Annotated[ModelRegistry, Depends(get_registry)],
    manager: Annotated[FallbackManager, Depends(get_fallback_manager)],
) -> QuizOut:
    document = documents_repo.get_document(db, user_id, body.document_id)
    if document is None:
        raise HTTPException(404, "Document not found")
    if document.status != "ready":
        raise HTTPException(409, "This document isn't ready yet: wait until it says Ready.")

    pieces = repo.document_pieces(db, document)
    try:
        draft = generate_quiz(manager, pieces, body.questions, registry.default_model("quiz"))
    except QuizFailed as e:
        calls_repo.log_llm_calls(db, user_id, None, e.attempts, "quiz")
        db.commit()  # the failed calls are kept; no quiz is saved
        raise HTTPException(503, str(e)) from e
    answered_by = next((a.model for a in reversed(draft.attempts) if a.status == "ok"), None)
    quiz = repo.create_quiz(db, user_id, document, draft, answered_by)
    calls_repo.log_llm_calls(db, user_id, None, draft.attempts, "quiz")
    db.commit()
    return quiz_out(quiz)


@router.get("", response_model=list[QuizSummary])
def list_quizzes(user_id: CurrentUserId, db: Db) -> list[QuizSummary]:
    quizzes = repo.list_quizzes(db, user_id)
    attempts = repo.attempts_of(db, user_id, [q.id for q in quizzes])
    summaries = []
    for quiz in quizzes:
        scores = [a.score for a in attempts if a.quiz_id == quiz.id]  # oldest first
        summaries.append(
            QuizSummary(
                id=quiz.id,
                title=quiz.title,
                document_id=quiz.document_id,
                document_name=quiz.document_name,
                created_at=as_utc(quiz.created_at),
                question_count=len(quiz.questions),
                attempts=len(scores),
                best_score=max(scores) if scores else None,
                last_score=scores[-1] if scores else None,
            )
        )
    return summaries


@router.get("/{quiz_id}", response_model=QuizOut)
def get_quiz(quiz_id: str, user_id: CurrentUserId, db: Db) -> QuizOut:
    return quiz_out(my_quiz(db, user_id, quiz_id))


@router.post("/{quiz_id}/attempts", response_model=AttemptOut, status_code=201)
def submit_attempt(quiz_id: str, body: AttemptIn, user_id: CurrentUserId, db: Db) -> AttemptOut:
    quiz = my_quiz(db, user_id, quiz_id)
    if len(body.answers) != len(quiz.questions):
        raise HTTPException(422, f"Send one answer per question ({len(quiz.questions)}).")
    results = [
        ResultOut(
            chosen=chosen,
            correct_answer=q["answer"],
            is_correct=chosen == q["answer"],  # skipped (None) is never correct
            explanation=q["explanation"],
            page=q["page"],
        )
        for chosen, q in zip(body.answers, quiz.questions, strict=True)
    ]
    score = sum(r.is_correct for r in results)
    attempt = repo.add_attempt(db, user_id, quiz, body.answers, score)
    db.commit()
    return AttemptOut(id=attempt.id, score=score, total=len(results), results=results)


@router.delete("/{quiz_id}", status_code=204)
def delete_quiz(quiz_id: str, user_id: CurrentUserId, db: Db) -> Response:
    db.delete(my_quiz(db, user_id, quiz_id))  # its attempts go too (CASCADE)
    db.commit()
    return Response(status_code=204)
