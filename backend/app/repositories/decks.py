"""Queries for flashcard decks and their reviews. SMA-64. Every lookup takes user_id."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CardReview, Deck


def create_deck(db: Session, user_id: str, **fields) -> Deck:
    deck = Deck(user_id=user_id, **fields)
    db.add(deck)
    db.flush()
    return deck


def list_decks(db: Session, user_id: str) -> list[Deck]:
    query = select(Deck).where(Deck.user_id == user_id).order_by(Deck.created_at.desc())
    return list(db.scalars(query))


def get_deck(db: Session, user_id: str, deck_id: str) -> Deck | None:
    return db.scalar(select(Deck).where(Deck.id == deck_id, Deck.user_id == user_id))


def add_review(db: Session, user_id: str, deck: Deck, card_index: int, knew: bool) -> None:
    db.add(CardReview(deck_id=deck.id, user_id=user_id, card_index=card_index, knew=knew))
    db.flush()


def latest_marks(db: Session, user_id: str, deck_ids: list[str]) -> dict[tuple[str, int], bool]:
    """(deck id, card) -> knew, from each card's LATEST review: the one that counts."""
    query = (
        select(CardReview)
        .where(CardReview.user_id == user_id, CardReview.deck_id.in_(deck_ids))
        .order_by(CardReview.created_at)
    )
    marks: dict[tuple[str, int], bool] = {}
    for review in db.scalars(query):  # oldest first: later reviews overwrite earlier ones
        marks[(review.deck_id, review.card_index)] = review.knew
    return marks
