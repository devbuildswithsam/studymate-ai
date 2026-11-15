"""In-memory conversation history. SMA-23.

A dict of message lists, keyed by (user_id, conversation_id) so one user can never read
another user's conversation. It lives in the server process: a restart forgets everything.
A real database replaces it in Stage 2 (guide: "history survives a server restart").
"""

import uuid
from functools import lru_cache

from app.services.llm.base import Message


class ConversationStore:
    def __init__(self):
        self._conversations: dict[tuple[str, str], list[Message]] = {}

    def create(self, user_id: str) -> str:
        """Start an empty conversation and return its new id."""
        conversation_id = str(uuid.uuid4())
        self._conversations[(user_id, conversation_id)] = []
        return conversation_id

    def messages(self, user_id: str, conversation_id: str) -> list[Message]:
        """A copy of the conversation's messages. KeyError if this user has no such conversation."""
        return list(self._conversations[(user_id, conversation_id)])

    def append(self, user_id: str, conversation_id: str, *messages: Message) -> None:
        self._conversations[(user_id, conversation_id)].extend(messages)


@lru_cache
def get_conversation_store() -> ConversationStore:
    """One store for the whole app (also a FastAPI dependency: tests use a fresh one)."""
    return ConversationStore()
