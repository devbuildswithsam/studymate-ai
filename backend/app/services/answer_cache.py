"""A cache for identical study questions (SMA-67, guide Stage 5 "Rate limiting & caching").

Students often ask the same question again in a new study chat on the same notes. The
checked answer (text + citations) is then reused instead of paying for another AI call.

"Identical" is decided by a key that includes EVERYTHING the answer depends on: the user
(answers are never shared between users), the documents, the question (ignoring case and
spaces), the earlier messages (a follow-up like "and the second one?" means something
different in every chat), and the model choice. Anything else that differs = a new call.

In memory, like the rate limits: one server process in v1.1, forgotten on restart. An
entry lives an hour, so an answer can't stay stale for long if a document changes.
Summaries were already cached in the database (SMA-50); quizzes and flashcards are not
cached on purpose: asking again should give NEW questions.
"""

import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from functools import lru_cache
from typing import Any

TTL_SECONDS = 3600  # one hour
MAX_ENTRIES = 500  # then the oldest goes (a few hundred answers: a few MB at most)


def cache_key(
    user_id: str,
    document_ids: list[str],
    question: str,
    history: list[dict[str, Any]],
    model_id: str | None,
    allow_fallback: bool,
) -> str:
    parts = {
        "user": user_id,
        "documents": sorted(document_ids),
        "question": " ".join(question.split()).casefold(),  # "  What IS x?" = "what is x?"
        "history": history,
        "model": model_id,
        "fallback": allow_fallback,
    }
    # A hash: short, and the question itself isn't kept in the key.
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


class AnswerCache:
    def __init__(
        self,
        ttl_seconds: float = TTL_SECONDS,
        max_entries: int = MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.clock = clock
        self._entries: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if self.clock() - stored_at > self.ttl_seconds:
                del self._entries[key]
                return None
            return value

    def put(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._entries[key] = (self.clock(), value)
            self._entries.move_to_end(key)  # newest last
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)  # the oldest first


@lru_cache
def get_answer_cache() -> AnswerCache:
    """One cache for the whole app. A FastAPI dependency: tests get a fresh one each."""
    return AnswerCache()
