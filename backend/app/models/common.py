"""Small helpers shared by the models. SMA-28."""

import uuid
from datetime import UTC, datetime


def new_id() -> str:
    """A random UUID string. Not 1, 2, 3...: ids appear in URLs and shouldn't be guessable."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Always store UTC; the browser converts to local time."""
    return datetime.now(UTC)


def as_utc(moment: datetime) -> datetime:
    """SQLite has no time-zone type: datetimes come back without one (but hold UTC). Mark
    them as UTC so they can be compared with utcnow() and sent to the browser as UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def allowed(column: str, values: tuple[str, ...]) -> str:
    """SQL for a CHECK constraint: the column must be one of `values` (NULL is allowed)."""
    return f"{column} IN ({', '.join(repr(v) for v in values)})"
