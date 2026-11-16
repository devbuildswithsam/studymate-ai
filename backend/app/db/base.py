"""The base class every SQLAlchemy model inherits from (models arrive in SMA-28). SMA-27.

Base.metadata collects every table the models define; Alembic compares it with the
database to write migrations.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Give every constraint and index a predictable name. Without names, a later
# migration can't drop or change a constraint, and SQLite needs names for that.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
