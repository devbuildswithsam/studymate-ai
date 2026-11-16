"""Turso compatibility spike (SMA-35). Throwaway code: NOT part of the app.

Runs our real SQLAlchemy models, repositories and Alembic migrations against a Turso dev
database (no real data), and prints PASS / FAIL / NOTE per check. Results: ADR-0006.

Run from backend/ with a separate venv that has backend/requirements.txt + libsql==0.1.11:
    <spike-venv>\\Scripts\\python ..\\experiments\\turso_spike\\spike.py
Needs TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in backend/.env. Never prints them.
"""

import sqlite3
import struct
import sys
import time
import traceback
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

import libsql  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from dotenv import dotenv_values  # noqa: E402
from sqlalchemy import (  # noqa: E402
    Column,
    LargeBinary,
    MetaData,
    String,
    Table,
    create_engine,
    event,
    exc,
    select,
    text,
)
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.types import UserDefinedType  # noqa: E402

import app.db.session  # noqa: E402
from app.models import Conversation, Message, Note, User  # noqa: E402
from app.repositories import conversations as conv_repo  # noqa: E402
from app.repositories import notes as notes_repo  # noqa: E402

ENV = dotenv_values(BACKEND / ".env")
URL, TOKEN = ENV["TURSO_DATABASE_URL"], ENV["TURSO_AUTH_TOKEN"]
RESULTS: list[tuple[str, str, str]] = []


def record(name: str, status: str, note: str = "") -> None:
    RESULTS.append((name, status, note))
    print(f"[{status:4}] {name}: {note}", flush=True)


def short(error: BaseException) -> str:
    return f"{type(error).__module__}.{type(error).__name__}: {str(error)[:160]}"


def connect_raw():
    return libsql.connect(URL, auth_token=TOKEN)


class LibsqlConnection:
    """Wrapper adding what SQLAlchemy's SQLite dialect expects but libsql lacks."""

    def __init__(self, connection):
        self._connection = connection

    def create_function(self, *args, **kwargs):  # SQLAlchemy registers REGEXP with it
        pass

    def __getattr__(self, name):
        return getattr(self._connection, name)


def make_turso_engine(pre_ping: bool = True):
    engine = create_engine(
        "sqlite://", creator=lambda: LibsqlConnection(connect_raw()), pool_pre_ping=pre_ping
    )
    # Same foreign-key setup as the app's make_engine().
    event.listen(engine, "connect", app.db.session._enable_sqlite_foreign_keys)
    return engine


def run(name: str, check) -> None:
    try:
        check()
    except BaseException as error:  # a spike: record everything (Rust panics too), keep going
        record(name, "FAIL", short(error))
        traceback.print_exc(limit=2)


# --- 1. Can SQLAlchemy use the driver at all? --------------------------------------


def check_plain_engine():
    engine = create_engine("sqlite://", creator=connect_raw)
    try:
        with engine.connect() as c:
            c.execute(text("select 1")).scalar()
        record("plain create_engine(creator=libsql.connect)", "PASS", "works without a wrapper")
    except Exception as error:
        record("plain create_engine(creator=libsql.connect)", "FAIL", short(error))
    finally:
        engine.dispose()


def check_wrapped_engine():
    engine = make_turso_engine()
    with engine.connect() as c:
        version = c.execute(text("select sqlite_version()")).scalar()
        fk = c.execute(text("PRAGMA foreign_keys")).scalar()
    engine.dispose()
    record("engine with a small wrapper", "PASS", f"SQLite {version}, foreign_keys={fk}")


# --- 2. Our real Alembic migrations ------------------------------------------------


def alembic_on_turso(engine) -> Config:
    # env.py builds its engine with make_engine(): hand it the Turso engine instead.
    app.db.session.make_engine = lambda url: engine
    config = Config(BACKEND / "alembic.ini")
    config.set_main_option("sqlalchemy.url", "sqlite://")  # ignored by the patched engine
    return config


def check_migrations():
    engine = make_turso_engine()
    config = alembic_on_turso(engine)
    command.downgrade(config, "base")  # start clean (dev database, no real data)
    t = time.perf_counter()
    command.upgrade(config, "head")
    seconds = time.perf_counter() - t
    with make_turso_engine().connect() as c:
        version = c.execute(text("select version_num from alembic_version")).scalar()
        tables = sorted(
            r[0]
            for r in c.execute(text("select name from sqlite_master where type='table'"))
            if not r[0].startswith(("sqlite_", "_"))
        )
    record(
        "alembic upgrade head (all 3 migrations)",
        "PASS",
        f"at {version} in {seconds:.1f} s; tables {tables}",
    )


def check_migration_round_trip_with_data():
    """SMA-33's worry: batch rebuilds with foreign keys on would cut links / delete rows."""
    engine = make_turso_engine()
    with Session(engine) as db:
        user = User(email="spike@example.com")
        db.add(user)
        db.flush()
        chat = conv_repo.create_conversation(db, user.id)
        conv_repo.add_message(db, chat, role="user", content="q")
        answer = conv_repo.add_message(db, chat, role="assistant", content="a")
        notes_repo.create_note(db, user.id, title="n", content="", tags=[], source_message=answer)
        db.commit()
        answer_id = answer.id
    config = alembic_on_turso(make_turso_engine())
    command.downgrade(config, "-1")  # rebuilds conversations (drops mode)
    command.downgrade(config, "-1")  # rebuilds messages (drops position)
    command.upgrade(config, "head")
    with make_turso_engine().connect() as c:
        messages = c.execute(text("select count(*) from messages")).scalar()
        link = c.execute(text("select source_message_id from notes")).scalar()
        broken = c.execute(text("PRAGMA foreign_key_check")).all()
    ok = messages == 2 and link == answer_id and not broken
    record(
        "downgrade x2 + upgrade with data (batch rebuilds)",
        "PASS" if ok else "FAIL",
        f"messages={messages}, note still linked={link == answer_id}, broken links={len(broken)}",
    )


# --- 3. CRUD, JSON, relationships, LIKE search (our real repositories) -------------


def check_crud_json_and_search():
    with Session(make_turso_engine(), expire_on_commit=False) as db:
        user = db.scalar(select(User).where(User.email == "spike@example.com"))
        chat = conv_repo.create_conversation(db, user.id, provider="gemini", model="m1")
        conv_repo.add_message(
            db, chat, role="assistant", content="F = m * a", citations=[{"doc": "a.pdf", "page": 3}]
        )
        note = notes_repo.create_note(
            db, user.id, title="Newton 100% sure", content="F = m * a", tags=["physics", "exam"]
        )
        db.commit()
        conv_repo.rename_conversation(db, user.id, chat.id, "Physics")
        db.commit()
        found = conv_repo.get_conversation(db, user.id, chat.id, with_messages=True)
        citations = found.messages[-1].citations
        tags = db.get(Note, note.id).tags
        by_tag = [n.title for n in notes_repo.search_notes(db, user.id, "EXAM")]
        by_percent = [n.title for n in notes_repo.search_notes(db, user.id, "%")]
        listed = [c.title for c in conv_repo.list_conversations(db, user.id)]
        conv_repo.delete_conversation(db, user.id, chat.id)
        db.commit()
        gone = conv_repo.get_conversation(db, user.id, chat.id) is None
    ok = (
        citations == [{"doc": "a.pdf", "page": 3}]
        and tags == ["physics", "exam"]
        and by_tag == ["Newton 100% sure"]
        and by_percent == ["Newton 100% sure"]
        and "Physics" in listed
        and gone
    )
    record(
        "CRUD + JSON + selectinload + LIKE/ESCAPE search",
        "PASS" if ok else "FAIL",
        f"json={citations == [{'doc': 'a.pdf', 'page': 3}]}, tags={tags}, search tag={by_tag}, "
        f"search '%'={by_percent}, renamed listed={'Physics' in listed}, deleted={gone}",
    )


# --- 4. BLOB embeddings ------------------------------------------------------------


class RawBlob(UserDefinedType):
    """A BLOB column that sends plain bytes. LargeBinary sends a memoryview (that's what
    sqlite3 wants), and libsql refuses it: 'Unsupported parameter type <memory>'."""

    cache_ok = True

    def get_col_spec(self, **kwargs):
        return "BLOB"


def check_blob_large_binary():
    metadata = MetaData()
    table = Table(
        "spike_lb", metadata, Column("id", String(36), primary_key=True), Column("b", LargeBinary)
    )
    engine = make_turso_engine()
    metadata.drop_all(engine)
    metadata.create_all(engine)
    try:
        with engine.begin() as c:
            c.execute(table.insert(), [{"id": "x", "b": b"abc"}])
        record("BLOB with SQLAlchemy LargeBinary", "PASS", "works as is")
    except BaseException as error:
        record("BLOB with SQLAlchemy LargeBinary", "FAIL", short(error))
    finally:
        metadata.drop_all(engine)


def check_blob_embeddings():
    metadata = MetaData()
    vectors = Table(
        "spike_vectors",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("embedding", RawBlob()),
    )
    engine = make_turso_engine()
    metadata.drop_all(engine)
    metadata.create_all(engine)
    dims = 768  # a typical embedding size
    original = [i / dims for i in range(dims)]
    blob = struct.pack(f"{dims}f", *original)  # float32, like NumPy's tobytes()
    with engine.begin() as c:
        c.execute(vectors.insert(), [{"id": "v1", "embedding": blob}])
        t = time.perf_counter()
        c.execute(vectors.insert(), [{"id": f"b{i}", "embedding": blob} for i in range(200)])
        insert_ms = (time.perf_counter() - t) * 1000
    with engine.connect() as c:
        back = c.execute(select(vectors.c.embedding).where(vectors.c.id == "v1")).scalar()
        t = time.perf_counter()
        all_rows = c.execute(select(vectors.c.embedding)).all()
        read_ms = (time.perf_counter() - t) * 1000
    same = back == blob and list(struct.unpack(f"{dims}f", back)) == list(
        struct.unpack(f"{dims}f", blob)
    )
    metadata.drop_all(engine)
    record(
        "BLOB float32 embeddings (768 dims), with RawBlob",
        "PASS" if same else "FAIL",
        f"exact bytes back={same}; insert 200: {insert_ms:.0f} ms; read {len(all_rows)}: {read_ms:.0f} ms",
    )


# --- 5. Transactions and foreign keys ----------------------------------------------


def check_transactions():
    engine = make_turso_engine()
    with Session(engine) as db:
        db.add(User(email="rollback@example.com"))
        db.flush()
        db.rollback()
        db.add(User(email="commit@example.com"))
        db.commit()
    with Session(engine) as db:
        rolled_back = db.scalar(select(User).where(User.email == "rollback@example.com")) is None
        committed = db.scalar(select(User).where(User.email == "commit@example.com")) is not None
    record(
        "transactions: rollback discards, commit keeps",
        "PASS" if rolled_back and committed else "FAIL",
        f"rolled back gone={rolled_back}, committed kept={committed}",
    )


def check_foreign_keys():
    engine = make_turso_engine()
    with Session(engine) as db:
        db.add(Conversation(user_id="no-such-user"))
        try:
            db.commit()
            enforced = False
        except Exception as error:
            enforced = "FOREIGN KEY" in str(error).upper()
            db.rollback()
    with Session(engine) as db:  # ON DELETE CASCADE, done by the database itself
        user = User(email="cascade@example.com")
        chat = Conversation(user=user)
        chat.messages.append(Message(position=1, role="user", content="x"))
        db.add(user)
        db.commit()
        chat_id = chat.id  # read it now: after the cascade the row is gone
        db.execute(text("DELETE FROM users WHERE email = 'cascade@example.com'"))
        db.commit()
        left = db.scalar(text("select count(*) from conversations where id = :id"), {"id": chat_id})
    record(
        "foreign keys enforced + ON DELETE CASCADE",
        "PASS" if enforced and left == 0 else "FAIL",
        f"orphan refused={enforced}, cascade deleted chat={left == 0}",
    )


# --- 6. Errors ---------------------------------------------------------------------


def check_error_types():
    engine = make_turso_engine()
    with Session(engine) as db:
        db.add(User(email="commit@example.com"))  # duplicate email
        try:
            db.commit()
            record("duplicate email -> IntegrityError", "FAIL", "no error at all")
            return
        except exc.IntegrityError as error:
            record("duplicate email -> sqlalchemy IntegrityError", "PASS", short(error.orig))
        except Exception as error:
            record(
                "duplicate email -> sqlalchemy IntegrityError",
                "FAIL",
                f"got {short(error)} (sqlite3.Error: {isinstance(error, sqlite3.Error)}, "
                f"sqlalchemy DBAPIError: {isinstance(error, exc.DBAPIError)})",
            )
        finally:
            db.rollback()


def check_bad_token():
    bad = libsql.connect(URL, auth_token="not-a-valid-token")
    try:
        bad.execute("select 1").fetchone()
        record("wrong auth token", "FAIL", "query succeeded with a bad token?!")
    except Exception as error:
        message = str(error)
        record(
            "wrong auth token",
            "NOTE",
            f"{type(error).__name__}, mentions 401/unauthorized: "
            f"{'401' in message or 'nauthor' in message}; leaks token: {'not-a-valid-token' in message}",
        )


# --- 7. A dropped connection -------------------------------------------------------


def drop_pooled_connection(engine) -> None:
    """Close the real connection behind the pool's back, like a network drop would."""
    raw = engine.raw_connection()
    raw.dbapi_connection._connection.close()
    try:
        raw.close()  # back to the pool, now dead: the pool's rollback on return may panic
    except BaseException as error:
        record("returning a dropped connection to the pool", "FAIL", short(error))


def try_query(engine) -> str:
    try:
        with engine.connect() as c:
            c.execute(text("select 1")).scalar()
        return "recovered"
    except BaseException as error:
        return f"{short(error)[:90]}"


def check_reconnect():
    with_ping = make_turso_engine(pre_ping=True)
    with_ping.connect().close()
    drop_pooled_connection(with_ping)
    without_ping = make_turso_engine(pre_ping=False)
    without_ping.connect().close()
    drop_pooled_connection(without_ping)
    a, b = try_query(with_ping), try_query(without_ping)
    record(
        "reconnect after a dropped connection",
        "PASS" if a == "recovered" else "FAIL",
        f"pool_pre_ping=True: {a}; without: {b}",
    )


# --- 8. Speed ----------------------------------------------------------------------


def check_latency():
    engine = make_turso_engine()
    with engine.connect() as c:
        times = []
        for _ in range(20):
            t = time.perf_counter()
            c.execute(text("select 1")).scalar()
            times.append((time.perf_counter() - t) * 1000)
    with Session(engine) as db:  # what the app does to load one chat with its messages
        user = db.scalar(select(User).where(User.email == "spike@example.com"))
        chat = conv_repo.create_conversation(db, user.id)
        for n in range(10):
            conv_repo.add_message(db, chat, role="user", content=f"m{n}")
        db.commit()
        t = time.perf_counter()
        conv_repo.get_conversation(db, user.id, chat.id, with_messages=True)
        load_ms = (time.perf_counter() - t) * 1000
    times.sort()
    record(
        "latency",
        "NOTE",
        f"SELECT 1 median {times[10]:.0f} ms (min {times[0]:.0f}); load chat + 10 messages: {load_ms:.0f} ms",
    )


def cleanup():
    command.downgrade(alembic_on_turso(make_turso_engine()), "base")
    with make_turso_engine().connect() as c:
        left = [r[0] for r in c.execute(text("select name from sqlite_master where type='table'"))]
    record(
        "cleanup (downgrade base)",
        "PASS" if not [t for t in left if not t.startswith("_")] else "NOTE",
        f"tables left: {left}",
    )


if __name__ == "__main__":
    for name, check in [
        ("plain engine", check_plain_engine),
        ("wrapped engine", check_wrapped_engine),
        ("migrations", check_migrations),
        ("migration round trip", check_migration_round_trip_with_data),
        ("crud", check_crud_json_and_search),
        ("blob large binary", check_blob_large_binary),
        ("blob", check_blob_embeddings),
        ("transactions", check_transactions),
        ("foreign keys", check_foreign_keys),
        ("errors", check_error_types),
        ("bad token", check_bad_token),
        ("reconnect", check_reconnect),
        ("latency", check_latency),
        ("cleanup", cleanup),
    ]:
        run(name, check)
    print("\nSUMMARY")
    for name, status, _note in RESULTS:
        print(f"  {status:4}  {name}")
