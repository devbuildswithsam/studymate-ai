"""Queries for personal access tokens. SMA-61.

Every lookup takes user_id, except find_by_hash: /mcp knows only the token, and the token
IS the proof of who the user is.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AccessToken


def list_tokens(db: Session, user_id: str) -> list[AccessToken]:
    query = select(AccessToken).where(AccessToken.user_id == user_id)
    return list(db.scalars(query.order_by(AccessToken.created_at.desc())))


def count_tokens(db: Session, user_id: str) -> int:
    query = select(func.count()).select_from(AccessToken).where(AccessToken.user_id == user_id)
    return db.scalar(query) or 0


def get_token(db: Session, user_id: str, token_id: str) -> AccessToken | None:
    query = select(AccessToken).where(AccessToken.id == token_id, AccessToken.user_id == user_id)
    return db.scalar(query)


def find_by_hash(db: Session, token_hash: str) -> AccessToken | None:
    return db.scalar(select(AccessToken).where(AccessToken.token_hash == token_hash))
