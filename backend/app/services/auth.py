"""Passwords, session tokens and login limits for real accounts. SMA-57 (ADR-0009).

Only well-known libraries do the cryptography: pwdlib (Argon2id) for passwords, PyJWT for
tokens. Nothing here is hand-made.
"""

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import cache, lru_cache

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError

SESSION_COOKIE = "studymate_session"
SESSION_LIFETIME = timedelta(hours=8)
ALGORITHM = "HS256"
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

# Argon2id with pwdlib's recommended settings (about 86 ms per hash, see the auth spike).
_hasher = PasswordHash.recommended()


# --- Passwords --------------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """The string to store: algorithm, settings, random salt and hash, never the password."""
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    """Does the password match? A user without a password (the local user) never matches."""
    if not stored_hash:
        return False
    try:
        return _hasher.verify(password, stored_hash)
    except PwdlibError:  # a damaged or unknown hash in the database: no match, no crash
        return False


# Public on purpose: knowing it must never help, because login also requires a real
# stored hash (tested in test_accounts.py).
DUMMY_PASSWORD = "no account has this password, it only costs time"


@cache
def dummy_hash() -> str:
    """A real hash, checked when the email is unknown or has no password.

    Login then does the same slow work whether or not the email exists, so its timing
    can't reveal who has an account. Made once, on first use.
    """
    return hash_password(DUMMY_PASSWORD)


# --- Session tokens ---------------------------------------------------------------------------


def create_session_token(user_id: str, secret: str, now: datetime | None = None) -> str:
    """A signed token saying "this is user_id" until it expires (8 hours)."""
    now = now or datetime.now(UTC)
    claims = {"sub": user_id, "iat": now, "exp": now + SESSION_LIFETIME}
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def read_session_token(token: str, secret: str) -> str | None:
    """The user id in a valid token, or None for anything else.

    algorithms=[ALGORITHM] is the important part: the token can't choose its own
    algorithm, so "alg: none" (no signature) is refused. PyJWT also checks the signature
    and the expiry, and `require` refuses tokens without them.
    """
    try:
        claims = jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["sub", "iat", "exp"]}
        )
    except jwt.InvalidTokenError:
        return None
    return claims["sub"]


# --- Guessing passwords ------------------------------------------------------------------------


class LoginLimiter:
    """After 5 failed logins for one email from one address, wait 15 minutes.

    Kept in memory: enough for one server process (v1.1). A restart forgets the counts.
    """

    def __init__(
        self,
        max_failures: int = 5,
        window: timedelta = timedelta(minutes=15),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.max_failures = max_failures
        self.window = window
        self.clock = clock
        self._failures: dict[tuple[str, str], list[datetime]] = {}
        self._lock = threading.Lock()  # sync routes run in several threads at once

    def _recent(self, key: tuple[str, str]) -> list[datetime]:
        cutoff = self.clock() - self.window
        recent = [moment for moment in self._failures.get(key, []) if moment > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)  # don't keep old entries forever
        return recent

    def allowed(self, email: str, address: str) -> bool:
        with self._lock:
            return len(self._recent((email, address))) < self.max_failures

    def failed(self, email: str, address: str) -> None:
        with self._lock:
            key = (email, address)
            self._failures[key] = [*self._recent(key), self.clock()]

    def succeeded(self, email: str, address: str) -> None:
        with self._lock:
            self._failures.pop((email, address), None)


@lru_cache
def get_login_limiter() -> LoginLimiter:
    """One limiter for the whole app (a FastAPI dependency, so tests get a fresh one)."""
    return LoginLimiter()
