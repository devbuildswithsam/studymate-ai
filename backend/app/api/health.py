"""GET /api/health: is the server up, and how is it configured? SMA-20.

Database and LLM reachability checks are added once those exist (later stages).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import APP_VERSION, Settings, get_settings

router = APIRouter(prefix="/api", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    env: str
    auth_mode: str


@router.get("/health", response_model=HealthResponse)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    # Depends(get_settings): FastAPI hands us the settings, so tests can swap them.
    return HealthResponse(
        status="ok", version=APP_VERSION, env=settings.env, auth_mode=settings.auth_mode
    )
