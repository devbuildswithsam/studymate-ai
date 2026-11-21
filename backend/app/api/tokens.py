"""Personal access tokens for MCP clients (Settings page). SMA-61.

GET    /api/tokens        my tokens (never the token itself: only a short prefix)
POST   /api/tokens        make one: {"name", "expires_in_days": 30 | 90 | 365}; the answer
                          holds the token, the ONLY time it is ever shown
DELETE /api/tokens/{id}   revoke it: /mcp refuses it from the next request on

The user comes only from get_current_user_id. Another user's token answers 404.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.db.session import get_db
from app.models.common import as_utc
from app.repositories import access_tokens as repo
from app.services import access_tokens as service

router = APIRouter(prefix="/api/tokens", tags=["tokens"])

CurrentUserId = Annotated[str, Depends(get_current_user_id)]
Db = Annotated[Session, Depends(get_db)]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class TokenCreate(BaseModel):
    name: Name
    expires_in_days: Literal[30, 90, 365] = service.DEFAULT_EXPIRY_DAYS


class TokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    prefix: str  # "smat_AbCdEfG": enough to tell tokens apart, useless to an attacker
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None

    # Sent as UTC ("...+00:00"), so the browser shows the right local time.
    @field_validator("created_at", "expires_at", "last_used_at")
    @classmethod
    def in_utc(cls, moment: datetime | None) -> datetime | None:
        return as_utc(moment) if moment else None


class NewTokenOut(TokenOut):
    token: str  # shown once: copy it now


@router.get("", response_model=list[TokenOut])
def list_tokens(user_id: CurrentUserId, db: Db) -> list:
    return repo.list_tokens(db, user_id)


@router.post("", response_model=NewTokenOut, status_code=201)
def create_token(body: TokenCreate, user_id: CurrentUserId, db: Db) -> NewTokenOut:
    if repo.count_tokens(db, user_id) >= service.MAX_TOKENS:
        raise HTTPException(
            409, f"You already have {service.MAX_TOKENS} tokens. Revoke one you don't use."
        )
    row, token = service.create_token(db, user_id, body.name, body.expires_in_days)
    return NewTokenOut(**TokenOut.model_validate(row).model_dump(), token=token)


@router.delete("/{token_id}", status_code=204)
def revoke_token(token_id: str, user_id: CurrentUserId, db: Db) -> Response:
    row = repo.get_token(db, user_id, token_id)
    if row is None:
        raise HTTPException(404, "Token not found")
    db.delete(row)
    db.commit()
    return Response(status_code=204)
