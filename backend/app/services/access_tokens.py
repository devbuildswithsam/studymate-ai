"""Personal access tokens: making them and checking them. SMA-61 (guide 7.2, ADR-0009).

A token looks like "smat_" + 43 random characters (32 random bytes). The prefix makes it
easy to recognise (and for secret scanners to spot if it's ever pasted somewhere public).
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import AccessToken, User
from app.models.common import as_utc, utcnow
from app.repositories import access_tokens as repo

TOKEN_PREFIX = "smat_"  # StudyMate access token
MAX_TOKENS = 10  # per user: enough for every MCP client you use
EXPIRY_DAYS = (30, 90, 365)
DEFAULT_EXPIRY_DAYS = 90


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256, fast on purpose: a 32-byte random token can't be guessed, so a slow hash
    (Argon2, for human passwords) would only slow down every /mcp request."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(db: Session, user_id: str, name: str, days: int) -> tuple[AccessToken, str]:
    """The stored row and the token itself, which the caller shows ONCE and then forgets."""
    token = new_token()
    row = AccessToken(
        user_id=user_id,
        name=name,
        token_hash=hash_token(token),
        prefix=token[:12],
        expires_at=utcnow() + timedelta(days=days),
    )
    db.add(row)
    db.commit()
    return row, token


def owner_of(db: Session, token: str) -> User | None:
    """The user a valid token belongs to, or None (unknown, deleted or expired).

    Records when it was used, so the Settings page can show forgotten tokens.
    """
    row = repo.find_by_hash(db, hash_token(token))
    now = utcnow()
    if row is None or as_utc(row.expires_at) <= now:
        return None
    row.last_used_at = now
    db.commit()
    return db.get(User, row.user_id)
