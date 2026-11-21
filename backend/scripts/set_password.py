"""Set or reset an account's password (the admin's tool). SMA-60, ADR-0009.

From backend/ with the venv active:
    python -m scripts.set_password local@studymate.dev
    python -m scripts.set_password ada@example.com --database-url sqlite:///./other.db

Two jobs:
- The v1.0 local user has no password. Give it one, and in accounts mode (AUTH_MODE=jwt)
  you log in as that user and find all your local-mode chats, notes and documents.
- "Forgot your password? Ask the admin": this is what the admin runs.

The password is typed twice and never shown, printed or logged. A session that is already
open stays valid until it expires (8 hours, ADR-0009).
"""

import argparse
import sys
from collections.abc import Callable
from getpass import getpass

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import make_engine
from app.repositories.users import find_user_by_email
from app.services.auth import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, hash_password


def password_problem(password: str) -> str | None:
    """The same rules as registering (app/api/auth.py)."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Use at least {PASSWORD_MIN_LENGTH} characters."
    if len(password) > PASSWORD_MAX_LENGTH:
        return f"Use at most {PASSWORD_MAX_LENGTH} characters."
    return None


def main(argv: list[str] | None = None, read_password: Callable[[str], str] = getpass) -> int:
    """0 when the password was set, 1 when nothing changed (the reason is on stderr)."""
    parser = argparse.ArgumentParser(description="Set or reset an account's password.")
    parser.add_argument("email", help="the account's email, e.g. local@studymate.dev")
    parser.add_argument("--database-url", help="default: DATABASE_URL from backend/.env")
    args = parser.parse_args(argv)
    email = args.email.strip().lower()  # the same email rules as login

    # getpass hides what you type, so the password never appears on screen.
    password = read_password(f"New password for {email}: ")
    if (problem := password_problem(password)) is not None:
        print(problem, "Nothing was changed.", file=sys.stderr)
        return 1
    if read_password("Type it again: ") != password:
        print("The two passwords didn't match. Nothing was changed.", file=sys.stderr)
        return 1

    engine = make_engine(args.database_url or get_settings().database_url)
    try:
        with Session(engine) as db:
            user = find_user_by_email(db, email)
            if user is None:
                print(f"No account with the email {email}. Nothing was changed.", file=sys.stderr)
                return 1
            user.password_hash = hash_password(password)
            db.commit()
    finally:
        engine.dispose()
    print(f"Password set for {email}. They can log in with it when AUTH_MODE=jwt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
