"""Who is making this request? Dependencies shared by several routers. SMA-23, SMA-29.

CLAUDE.md rule: every query is scoped by user_id taken from the request context,
never from the request body. Routes get the user ONLY through these dependencies.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.seed import find_local_user
from app.db.session import get_db
from app.models import User

# The addresses "this same computer" arrives from (IPv4 and IPv6 loopback).
LOOPBACK_HOSTS = {"127.0.0.1", "::1"}


def get_current_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """The user making this request.

    AUTH_MODE=local (v1.0): one seeded user, and only callers on this machine.
    Stage 5 adds AUTH_MODE=jwt here; routes that depend on this don't change.
    """
    if settings.auth_mode != "local":
        raise NotImplementedError(f"AUTH_MODE={settings.auth_mode} arrives in Stage 5")

    # Local mode trusts every caller as the one user, so a caller from another machine
    # (uvicorn started with --host 0.0.0.0 by mistake) must be refused.
    client_host = request.client.host if request.client else None
    if client_host not in LOOPBACK_HOSTS:
        raise HTTPException(403, "AUTH_MODE=local only accepts requests from this computer.")

    user = find_local_user(db)
    if user is None:
        # A setup step was missed: say exactly how to fix it.
        raise HTTPException(500, "The local user is missing. Run: python -m scripts.seed")
    return user


def get_current_user_id(user: Annotated[User, Depends(get_current_user)]) -> str:
    """Just the id, for code that only needs to scope queries."""
    return user.id
