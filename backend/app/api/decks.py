"""Flashcard decks (guide Stage 5 "flashcards"). SMA-64.

POST   /api/decks                 make one: {"document_id"} (10 cards) or {"message_id"}
                                  of one of my AI answers (up to 5 cards)
GET    /api/decks                 mine, newest first, with how many cards are known
GET    /api/decks/{id}            one deck: its cards, each with my latest mark
POST   /api/decks/{id}/reviews    {"card": n, "knew": true|false}, saved for Progress
DELETE /api/decks/{id}            delete it and its reviews

A card counts as known when its LATEST review says "knew it". The user comes only from
get_current_user_id. Another user's deck, document or answer answers 404.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.db.session import get_db
from app.models import Deck
from app.models.common import as_utc
from app.repositories import conversations as calls_repo
from app.repositories import decks as repo
from app.repositories import documents as documents_repo
from app.repositories import notes as notes_repo
from app.repositories import quizzes as quizzes_repo
from app.services.flashcards import CARDS_FROM, FlashcardsFailed, generate_cards
from app.services.llm.fallback import FallbackManager, get_fallback_manager
from app.services.llm.registry import ModelRegistry, get_registry
from app.services.rate_limits import rate_limit

router = APIRouter(prefix="/api/decks", tags=["flashcards"])

CurrentUserId = Annotated[str, Depends(get_current_user_id)]
Db = Annotated[Session, Depends(get_db)]


class DeckCreate(BaseModel):
    document_id: str | None = None
    message_id: str | None = None  # an AI answer from one of my chats

    @model_validator(mode="after")
    def exactly_one_source(self) -> "DeckCreate":
        if (self.document_id is None) == (self.message_id is None):
            raise ValueError("send either document_id or message_id")
        return self


class CardOut(BaseModel):
    front: str
    back: str
    page: int | None
    last: Literal["knew", "didnt"] | None  # my latest mark for this card; None: not yet


class DeckSummary(BaseModel):
    id: str
    title: str
    source_type: Literal["document", "answer"]
    source_name: str
    created_at: datetime
    card_count: int
    reviewed: int  # cards marked at least once
    known: int  # cards whose latest mark is "knew it"


class DeckOut(DeckSummary):
    cards: list[CardOut]


class ReviewIn(BaseModel):
    card: int
    knew: bool


class ReviewOut(BaseModel):
    card_count: int
    reviewed: int
    known: int


def summary_fields(deck: Deck, marks: dict[tuple[str, int], bool]) -> dict:
    mine = [marks[(deck.id, i)] for i in range(len(deck.cards)) if (deck.id, i) in marks]
    return {
        "id": deck.id,
        "title": deck.title,
        "source_type": deck.source_type,
        "source_name": deck.source_name,
        "created_at": as_utc(deck.created_at),
        "card_count": len(deck.cards),
        "reviewed": len(mine),
        "known": sum(mine),
    }


def deck_out(deck: Deck, marks: dict[tuple[str, int], bool]) -> DeckOut:
    def last(i: int) -> Literal["knew", "didnt"] | None:
        if (deck.id, i) not in marks:
            return None
        return "knew" if marks[(deck.id, i)] else "didnt"

    cards = [CardOut(**card, last=last(i)) for i, card in enumerate(deck.cards)]
    return DeckOut(**summary_fields(deck, marks), cards=cards)


def my_deck(db: Session, user_id: str, deck_id: str) -> Deck:
    deck = repo.get_deck(db, user_id, deck_id)
    if deck is None:
        raise HTTPException(404, "Deck not found")
    return deck


@router.post(
    "",
    response_model=DeckOut,
    status_code=201,
    dependencies=[Depends(rate_limit("generate"))],  # SMA-67
)
def create_deck(
    body: DeckCreate,
    user_id: CurrentUserId,
    db: Db,
    registry: Annotated[ModelRegistry, Depends(get_registry)],
    manager: Annotated[FallbackManager, Depends(get_fallback_manager)],
) -> DeckOut:
    if body.document_id is not None:
        document = documents_repo.get_document(db, user_id, body.document_id)
        if document is None:
            raise HTTPException(404, "Document not found")
        if document.status != "ready":
            raise HTTPException(409, "This document isn't ready yet: wait until it says Ready.")
        source = "document"
        pieces = quizzes_repo.document_pieces(db, document)
        links = {"document_id": document.id, "source_name": document.filename}
    else:
        message = notes_repo.my_message(db, user_id, body.message_id)
        if message is None:
            raise HTTPException(404, "Message not found")
        if message.role != "assistant":
            raise HTTPException(400, "Flashcards are made from the AI's answers, not questions.")
        source = "answer"
        pieces = [(None, message.content)]
        name = message.conversation.title or "A chat answer"
        links = {"message_id": message.id, "source_name": name}

    try:
        draft = generate_cards(
            manager, pieces, CARDS_FROM[source], source, registry.default_model("quiz")
        )
    except FlashcardsFailed as e:
        calls_repo.log_llm_calls(db, user_id, None, e.attempts, "flashcards")
        db.commit()  # the failed calls are kept; no deck is saved
        raise HTTPException(503, str(e)) from e
    answered_by = next((a.model for a in reversed(draft.attempts) if a.status == "ok"), None)
    deck = repo.create_deck(
        db,
        user_id,
        title=draft.title,
        source_type=source,
        cards=draft.cards,
        model=answered_by,
        **links,
    )
    calls_repo.log_llm_calls(db, user_id, None, draft.attempts, "flashcards")
    db.commit()
    return deck_out(deck, {})


@router.get("", response_model=list[DeckSummary])
def list_decks(user_id: CurrentUserId, db: Db) -> list[DeckSummary]:
    decks = repo.list_decks(db, user_id)
    marks = repo.latest_marks(db, user_id, [d.id for d in decks])
    return [DeckSummary(**summary_fields(d, marks)) for d in decks]


@router.get("/{deck_id}", response_model=DeckOut)
def get_deck(deck_id: str, user_id: CurrentUserId, db: Db) -> DeckOut:
    deck = my_deck(db, user_id, deck_id)
    return deck_out(deck, repo.latest_marks(db, user_id, [deck.id]))


@router.post("/{deck_id}/reviews", response_model=ReviewOut, status_code=201)
def add_review(deck_id: str, body: ReviewIn, user_id: CurrentUserId, db: Db) -> ReviewOut:
    deck = my_deck(db, user_id, deck_id)
    if not 0 <= body.card < len(deck.cards):
        raise HTTPException(422, f"This deck has cards 0 to {len(deck.cards) - 1}.")
    repo.add_review(db, user_id, deck, body.card, body.knew)
    db.commit()
    marks = repo.latest_marks(db, user_id, [deck.id])
    fields = summary_fields(deck, marks)
    return ReviewOut(
        card_count=fields["card_count"], reviewed=fields["reviewed"], known=fields["known"]
    )


@router.delete("/{deck_id}", status_code=204)
def delete_deck(deck_id: str, user_id: CurrentUserId, db: Db) -> Response:
    db.delete(my_deck(db, user_id, deck_id))  # its reviews go too (CASCADE)
    db.commit()
    return Response(status_code=204)
