"""Dependencies shared by several routers. SMA-23.

CLAUDE.md rule: every query is scoped by user_id taken from the request context,
never from the request body.
"""

from typing import Annotated

from fastapi import Depends

from app.config import Settings, get_settings

LOCAL_USER_ID = "local"


def get_current_user_id(settings: Annotated[Settings, Depends(get_settings)]) -> str:
    """Who is making this request.

    AUTH_MODE=local (development on 127.0.0.1 only): there is one user, "local".
    Stage 5 replaces this with real login; routes that use it don't change.
    """
    if settings.auth_mode == "local":
        return LOCAL_USER_ID
    raise NotImplementedError(f"AUTH_MODE={settings.auth_mode} arrives in Stage 5")
