"""Per-user rate limits (SMA-67, guide Stage 5 "Rate limiting & caching").

Every AI call costs money or free-tier quota, so one user (or a stolen session, or a
script) must not be able to fire hundreds of them. A "sliding window": at most N actions
in any 60 seconds, counted per user and per kind of action.

Kept in memory, like the login limiter (SMA-57): enough for one server process in v1.1.
A restart forgets the counts; several server processes would each count on their own
(then a shared store such as Redis would be needed).
"""

import math
import threading
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException

from app.api.deps import get_current_user_id

# kind -> (most actions allowed, in this many seconds)
LIMITS: dict[str, tuple[int, int]] = {
    "chat": (20, 60),  # chat messages, normal or streamed
    "upload": (5, 60),  # document uploads (each one is embedded and summarised)
    "generate": (5, 60),  # quizzes and flashcard decks, together
}

# How each kind is named in the 429 message.
WHAT = {"chat": "messages", "upload": "uploads", "generate": "quizzes or flashcards"}


class RateLimiter:
    def __init__(
        self,
        limits: dict[str, tuple[int, int]] = LIMITS,
        clock: Callable[[], float] = time.monotonic,  # tests pass a clock they move by hand
    ) -> None:
        self.limits = limits
        self.clock = clock
        self._moments: dict[tuple[str, str], list[float]] = {}  # (user, kind) -> times
        self._lock = threading.Lock()  # sync routes run in several threads at once

    def hit(self, user_id: str, kind: str) -> int | None:
        """Count one action. None if it's allowed; otherwise the seconds to wait.

        A refused action isn't counted: hammering the button doesn't push the reset away.
        """
        most, seconds = self.limits[kind]
        now = self.clock()
        with self._lock:
            key = (user_id, kind)
            recent = [t for t in self._moments.get(key, []) if t > now - seconds]
            if len(recent) >= most:
                self._moments[key] = recent
                # The oldest one leaves the window first; then there is room again.
                # (It's still inside the window, so this is always at least 1 second.)
                return math.ceil(recent[0] + seconds - now)
            self._moments[key] = [*recent, now]
            return None


@lru_cache
def get_rate_limiter() -> RateLimiter:
    """One limiter for the whole app. A FastAPI dependency: tests swap it."""
    return RateLimiter()


def rate_limit(kind: str):
    """A route dependency: `dependencies=[Depends(rate_limit("chat"))]`.

    The user id comes from the session (never from the request body), so the limit can't
    be dodged by claiming to be someone else.
    """

    def check(
        user_id: Annotated[str, Depends(get_current_user_id)],
        limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ) -> None:
        wait = limiter.hit(user_id, kind)
        if wait is not None:
            raise HTTPException(
                429,
                f"Too many {WHAT[kind]} in a short time. Please try again in {wait} seconds.",
                headers={"Retry-After": str(wait)},
            )

    return check
