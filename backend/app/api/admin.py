"""GET /api/admin/usage: AI calls, failures and tokens per model and per day. SMA-68.

Admins only (`require_admin`): the emails in ADMIN_EMAILS, or the local user in
AUTH_MODE=local. The numbers cover EVERY user (that's what an admin needs to watch the
free-tier quotas), so they are totals only: no user, chat or question appears.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Integer, case, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models import LLMCall, User

router = APIRouter(prefix="/api/admin", tags=["admin"])


def is_admin(user: User, settings: Settings) -> bool:
    if settings.auth_mode == "local":
        return True  # the one local user, on your own computer
    admins = {email.strip().casefold() for email in settings.admin_emails.split(",")}
    return user.email.casefold() in admins - {""}


def require_admin(
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    if not is_admin(user, settings):
        raise HTTPException(403, "Only an admin can see this page.")
    return user


class UsageRow(BaseModel):
    day: str  # YYYY-MM-DD, in UTC
    provider: str
    model: str
    calls: int
    failures: int
    tokens_in: int
    tokens_out: int


class UsageTotals(BaseModel):
    calls: int
    failures: int
    tokens_in: int
    tokens_out: int


class Usage(BaseModel):
    days: int
    rows: list[UsageRow]  # newest day first, then by model
    totals: UsageTotals


@router.get("/usage", response_model=Usage, dependencies=[Depends(require_admin)])
def usage(
    db: Annotated[Session, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> Usage:
    since = datetime.now(UTC) - timedelta(days=days)
    day = func.date(LLMCall.created_at)
    failed = func.sum(case((LLMCall.status != "ok", 1), else_=0), type_=Integer)
    rows = db.execute(
        select(
            day.label("day"),
            LLMCall.provider,
            LLMCall.model,
            func.count().label("calls"),
            failed.label("failures"),
            func.coalesce(func.sum(LLMCall.tokens_in), 0).label("tokens_in"),
            func.coalesce(func.sum(LLMCall.tokens_out), 0).label("tokens_out"),
        )
        .where(LLMCall.created_at >= since)
        .group_by(day, LLMCall.provider, LLMCall.model)
        .order_by(day.desc(), LLMCall.model)
    ).all()
    usage_rows = [UsageRow(**row._mapping) for row in rows]
    return Usage(
        days=days,
        rows=usage_rows,
        totals=UsageTotals(
            calls=sum(r.calls for r in usage_rows),
            failures=sum(r.failures for r in usage_rows),
            tokens_in=sum(r.tokens_in for r in usage_rows),
            tokens_out=sum(r.tokens_out for r in usage_rows),
        ),
    )
