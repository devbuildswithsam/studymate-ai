"""The admin's password script: python -m scripts.set_password <email>. SMA-60.

Two jobs: give the v1.0 local user a password, so its data can be used with real accounts
(AUTH_MODE=jwt), and reset a forgotten password ("ask the admin", SMA-59). Test-first.
The password is typed twice and never shown or printed.
"""

from sqlalchemy import select

from app.db.seed import LOCAL_USER_EMAIL, ensure_local_user
from app.models import Note, User
from app.services.auth import verify_password
from scripts import set_password

NEW = "my new long password"


def typed(*answers: str):
    """Fake getpass: returns the given answers in order, like a person typing them."""
    remaining = list(answers)
    return lambda prompt="": remaining.pop(0)


def run(db_url, *args, answers=(NEW, NEW)) -> int:
    return set_password.main([*args, "--database-url", db_url], read_password=typed(*answers))


def stored_hash(db_session, email: str) -> str | None:
    db_session.expire_all()
    return db_session.scalar(select(User.password_hash).where(User.email == email))


def test_the_local_user_gets_a_password_and_keeps_its_data(db_url, db_session, jwt_api):
    local = ensure_local_user(db_session)
    db_session.add(Note(user_id=local.id, title="Made in local mode", content=""))
    db_session.commit()

    assert run(db_url, LOCAL_USER_EMAIL) == 0

    # In accounts mode the local user can now log in, and finds its v1.0 data.
    login = jwt_api.post("/api/auth/login", json={"email": LOCAL_USER_EMAIL, "password": NEW})
    assert login.status_code == 200
    assert [n["title"] for n in jwt_api.get("/api/notes").json()] == ["Made in local mode"]


def test_a_forgotten_password_is_replaced(db_url, db_session):
    db_session.add(User(email="ada@example.com", password_hash="$argon2id$old"))
    db_session.commit()

    assert run(db_url, "ADA@Example.com ") == 0  # same email rules as login

    assert verify_password(NEW, stored_hash(db_session, "ada@example.com"))


def test_the_password_is_never_printed(db_url, db_session, capsys):
    ensure_local_user(db_session)

    run(db_url, LOCAL_USER_EMAIL)

    output = capsys.readouterr()
    assert NEW not in output.out + output.err
    assert "Password set for local@studymate.dev" in output.out


def test_two_different_answers_change_nothing(db_url, db_session, capsys):
    ensure_local_user(db_session)

    assert run(db_url, LOCAL_USER_EMAIL, answers=(NEW, NEW + "x")) == 1

    assert "didn't match" in capsys.readouterr().err
    assert stored_hash(db_session, LOCAL_USER_EMAIL) is None


def test_a_too_short_password_changes_nothing(db_url, db_session, capsys):
    ensure_local_user(db_session)

    assert run(db_url, LOCAL_USER_EMAIL, answers=("short", "short")) == 1

    assert "at least 8" in capsys.readouterr().err
    assert stored_hash(db_session, LOCAL_USER_EMAIL) is None


def test_an_unknown_email_is_reported(db_url, capsys):
    assert run(db_url, "nobody@example.com") == 1

    assert "No account with the email nobody@example.com" in capsys.readouterr().err
