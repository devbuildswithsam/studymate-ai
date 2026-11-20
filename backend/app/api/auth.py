"""Accounts: register, login, logout, and who am I. SMA-57 (ADR-0009).

POST /api/auth/register   create an account and log in       (AUTH_MODE=jwt only)
POST /api/auth/login      email + password -> session cookie (AUTH_MODE=jwt only)
POST /api/auth/logout     delete the session cookie
GET  /api/auth/me         the signed-in user (in local mode: the local user)

The session is a signed token in an HttpOnly cookie: JavaScript can't read it, the
browser sends it with every request, and get_current_user checks it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models import User
from app.repositories import users as repo
from app.services import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])

Db = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
Limiter = Annotated[auth.LoginLimiter, Depends(auth.get_login_limiter)]

LOGIN_FAILED = "Email or password is incorrect."  # the same for both mistakes (ADR-0009)

# Spaces trimmed and lower-cased first, so "Ada@Example.com " and "ada@example.com" are one
# account. A light format check only: a real "is this your email?" needs an email service.
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]
# Never trimmed: spaces can be part of a password. A maximum, so no one can make us hash
# a megabyte. No "must contain a symbol" rules (ADR-0009).
NewPassword = Annotated[
    str,
    StringConstraints(min_length=auth.PASSWORD_MIN_LENGTH, max_length=auth.PASSWORD_MAX_LENGTH),
]
Password = Annotated[str, StringConstraints(max_length=auth.PASSWORD_MAX_LENGTH)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class RegisterIn(BaseModel):
    email: Email
    password: NewPassword
    name: Name | None = None


class LoginIn(BaseModel):
    email: Email
    password: Password


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str | None


def require_accounts(settings: Settings) -> None:
    if settings.auth_mode != "jwt":
        raise HTTPException(
            400, "Accounts are off: AUTH_MODE=local always uses the one local user."
        )


def start_session(response: Response, user: User, settings: Settings) -> None:
    """Log the user in: put a fresh signed token in the session cookie."""
    token = auth.create_session_token(user.id, settings.jwt_secret.get_secret_value())
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=int(auth.SESSION_LIFETIME.total_seconds()),
        path="/",
        secure=True,  # only over HTTPS (browsers also allow http://localhost)
        httponly=True,  # JavaScript can't read it, so an injected script can't steal it
        samesite="lax",  # not sent with requests that other websites start (CSRF: SMA-58)
    )


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, response: Response, settings: AppSettings, db: Db) -> User:
    require_accounts(settings)
    if repo.find_user_by_email(db, body.email):
        raise HTTPException(409, "An account with this email already exists. Log in instead.")
    user = repo.create_user(db, body.email, auth.hash_password(body.password), body.name)
    start_session(response, user, settings)
    return user


@router.post("/login", response_model=UserOut)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    settings: AppSettings,
    db: Db,
    limiter: Limiter,
) -> User:
    require_accounts(settings)
    address = request.client.host if request.client else "unknown"
    if not limiter.allowed(body.email, address):
        raise HTTPException(429, "Too many failed logins. Please wait 15 minutes and try again.")

    user = repo.find_user_by_email(db, body.email)
    stored_hash = user.password_hash if user else None
    # Always check one hash, even for an unknown email, so both cases take the same time.
    matches = auth.verify_password(body.password, stored_hash or auth.dummy_hash())
    # `stored_hash` too: a match against the dummy hash must never log anyone in.
    if user is None or stored_hash is None or not matches:
        limiter.failed(body.email, address)
        raise HTTPException(401, LOGIN_FAILED)

    limiter.succeeded(body.email, address)
    start_session(response, user, settings)
    return user


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    # The browser drops the cookie. The token itself stays valid until it expires (no
    # server-side session list, ADR-0009), but nothing keeps a copy of it.
    response.delete_cookie(
        auth.SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax"
    )


@router.get("/me", response_model=UserOut)
def me(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user
