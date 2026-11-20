"""Finding and creating user accounts. SMA-57.

The one place that looks users up by email (login, register) or by id (the session
cookie). Emails arrive already lower-cased by the API.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User


def get_user(db: Session, user_id: str) -> User | None:
    return db.get(User, user_id)


def find_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def create_user(db: Session, email: str, password_hash: str, name: str | None) -> User:
    user = User(email=email, password_hash=password_hash, name=name)
    db.add(user)
    db.commit()
    return user
