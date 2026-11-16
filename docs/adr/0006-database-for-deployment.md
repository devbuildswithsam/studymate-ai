# ADR-0006: Database for deployment: Turso does not pass the spike; v1.0 stays on SQLite

- **Status:** Accepted
- **Date:** 2026-11-16
- **Tickets:** SMA-35 (spike), SMA-33 (migrations without data loss)

## Context
Locally the app uses a plain SQLite file. The v1.1 deployment (Vercel functions) has no
persistent disk, so the guide planned **Turso** (hosted libSQL, SQLite-compatible), with a
rule: *adopt it for v1.1 only if a compatibility spike passes; v1.0 stays on plain SQLite
either way.* The spike ran our **real** models, repositories and Alembic migrations against
a Turso dev database (no real data) from Windows, Python 3.12, SQLAlchemy 2.1.8, Alembic 1.20.1,
driver `libsql` 0.1.11, server SQLite 3.47.0. Code: `experiments/turso_spike/spike.py`.

## Results

| Check | Result |
|---|---|
| Install the planned SQLAlchemy dialect | ❌ `sqlalchemy-libsql` 0.2.0 needs `libsql-experimental`, which has **no Windows wheel** (needs a Rust build). The newer `libsql` driver installs, but has no dialect |
| SQLAlchemy engine with `libsql` | ⚠️ Only through a small wrapper: the connection lacks `create_function`, which SQLAlchemy's SQLite dialect calls |
| `alembic upgrade head` | ✅ all 3 migrations, ~15 s |
| **Downgrade + upgrade with data** | ❌ **Data loss**: every message deleted, a note's link cut. Turso ignores `PRAGMA foreign_keys=OFF`, so SQLite's table rebuild (batch mode) runs `ON DELETE` rules (our SMA-33 protection doesn't work there) |
| CRUD, JSON columns, `selectinload`, LIKE search with `ESCAPE` | ✅ |
| Transactions (rollback / commit), foreign keys, `ON DELETE CASCADE` | ✅ |
| BLOB embeddings (768 × float32) | ⚠️ `LargeBinary` fails (`Unsupported parameter type <memory>`); exact round trip with a custom type that sends `bytes`. **200 inserts took ~21 s** (one network round trip each) |
| Error handling | ❌ A UNIQUE violation arrives as a plain `ValueError("Hrana: … SQLITE_CONSTRAINT")`, not SQLAlchemy's `IntegrityError` (`libsql.Error` isn't a `sqlite3.Error`). A wrong token gives an unclear `ValueError` (it doesn't leak the token) |
| Dropped connection | ⚠️ The next query recovers, but handing the dead connection back to the pool raises a Rust `PanicException`, a **`BaseException`**: `except Exception` and FastAPI's error handler don't catch it |
| Latency (from India) | ⚠️ ~200 ms per query (min ~80 ms) vs ~0.05 ms local; loading a chat with 10 messages took ~670 ms |

## Decision
- **Turso is not adopted.** The spike did not pass: data loss in migrations, wrong error
  types, uncatchable panics, and no installable SQLAlchemy dialect on our dev machine.
- **v1.0 stays on plain SQLite** (no change; it never depended on this).
- **The v1.1 database is chosen at the start of v1.1**, by running *this same spike* against
  the candidates (see below). The spike script is kept so that comparison is cheap.

## Consequences
- Nothing changes in the app now. `requirements.txt` gets no new package; the spike used a
  separate throwaway environment.
- Whatever we pick for v1.1 must pass the same checks, especially **migrations with data
  both ways** (`tests/test_migrations.py`) and **errors mapped to SQLAlchemy exceptions**.
- Design rules that keep any choice open: every query goes through SQLAlchemy and the
  repositories, no SQLite-only SQL in the app code, embeddings stored as plain BLOBs, few
  queries per request (each costs a network round trip on any hosted database).
- `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` in `backend/.env` are only for the spike. The
  Turso dev database is left empty and can be deleted.

## Alternatives considered (for v1.1)
- **Hosted Postgres (Neon / Supabase free tiers)** with `psycopg`: mature SQLAlchemy dialect,
  real `ALTER TABLE` (no table rebuilds, so no cascade risk), proper error types, `pgvector`
  later. Cost: migrations and SQLite-specific bits (e.g. `PRAGMA`s, `rowid` in the SMA-30
  backfill) need testing on Postgres. Currently the favourite.
- **Turso again with a newer driver/dialect:** re-run the spike; adopt only if every ❌ above
  becomes ✅.
- **A host with a persistent disk** (a small VM / container with a volume) running plain
  SQLite: no driver change at all, but gives up the Vercel plan.
- **Work around the failures** (wrapper, custom BLOB type, migrations without table rebuilds,
  catching `BaseException`): possible, but that is fragile code to own for a learning project.
