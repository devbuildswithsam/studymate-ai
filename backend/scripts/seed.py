"""Create the local user in the database (run after `alembic upgrade head`). SMA-29.

From backend/ with the venv active:  python -m scripts.seed
Safe to run again: it never creates a second user.
"""

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.seed import ensure_local_user
from app.db.session import make_engine


def main() -> None:
    engine = make_engine(get_settings().database_url)
    with Session(engine) as session:
        user = ensure_local_user(session)
        print(f"Local user ready: {user.email} (id {user.id})")
    engine.dispose()


if __name__ == "__main__":
    main()
