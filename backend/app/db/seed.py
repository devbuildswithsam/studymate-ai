"""Seed data: the single local user of AUTH_MODE=local. SMA-29 (guide 7.1a).

Idempotent: running it again finds the existing user instead of adding a second one.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User

LOCAL_USER_EMAIL = "local@studymate.dev"


def find_local_user(session: Session) -> User | None:
    return session.scalar(select(User).where(User.email == LOCAL_USER_EMAIL))


def ensure_local_user(session: Session) -> User:
    """Return the local user, creating (and committing) it on the first run."""
    user = find_local_user(session)
    if user is None:
        user = User(email=LOCAL_USER_EMAIL, name="Local user")
        session.add(user)
        session.commit()
    return user
