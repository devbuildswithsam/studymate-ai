"""Alembic environment: how `alembic upgrade` / `alembic revision` connect. SMA-27.

- Database: the URL given to Alembic (tests pass a temp file), else the app's
  DATABASE_URL setting, so .env stays the single source.
- target_metadata = Base.metadata: what `alembic revision --autogenerate` compares
  the database against. Importing app.models fills it with every table (SMA-28).
"""

from logging.config import fileConfig

from alembic import context

import app.models  # noqa: F401  (registers the tables on Base.metadata)
from app.config import get_settings
from app.db.base import Base
from app.db.session import make_engine

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: the default would silence the app's own loggers
    # (e.g. the fallback "Config problem" error) whenever migrations run in-process.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def database_url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    """`alembic upgrade --sql`: print the SQL instead of running it."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Normal mode: connect and apply the migrations."""
    engine = make_engine(database_url())  # same engine setup as the app (foreign keys on)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite can't ALTER most things in place; "batch" mode rebuilds the table
            # behind the scenes, so migrations like "add a NOT NULL column" still work.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
