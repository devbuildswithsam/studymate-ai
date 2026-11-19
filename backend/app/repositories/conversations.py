"""Conversations, their messages and the llm_calls log. SMA-30.

"Not yours" and "doesn't exist" look the same here (None / False), so an endpoint can't
accidentally tell a user that someone else's conversation exists.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Conversation, Document, LLMCall, Message, conversation_documents
from app.models.common import utcnow
from app.services.llm.fallback import Attempt


def create_conversation(
    db: Session,
    user_id: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    mode: str = "general",
    documents: list[Document] | None = None,  # SMA-49: what a study chat may search
) -> Conversation:
    conversation = Conversation(
        user_id=user_id, provider=provider, model=model, mode=mode, documents=documents or []
    )
    db.add(conversation)
    db.flush()  # sends the INSERT (inside the transaction), so defaults like id are set
    return conversation


def list_conversations(db: Session, user_id: str) -> list[Conversation]:
    """The user's conversations, most recent activity first. One query, no messages."""
    query = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
    )
    return list(db.scalars(query))


def get_conversation(
    db: Session, user_id: str, conversation_id: str, *, with_messages: bool = False
) -> Conversation | None:
    """One of the user's conversations, or None (also when it belongs to someone else).

    with_messages: load all its messages in ONE extra query (selectinload), instead of
    a lazy query later. That's how we avoid N+1 queries.
    """
    query = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id
    )
    if with_messages:
        # Each message's actions too (SMA-43): one more query for all of them.
        query = query.options(
            selectinload(Conversation.messages).selectinload(Message.actions),
            selectinload(Conversation.documents),  # SMA-49: a study chat's documents
        )
    return db.scalar(query)


def rename_conversation(
    db: Session, user_id: str, conversation_id: str, title: str
) -> Conversation | None:
    conversation = get_conversation(db, user_id, conversation_id)
    if conversation is not None:
        conversation.title = title
        db.flush()
    return conversation


def delete_conversation(db: Session, user_id: str, conversation_id: str) -> bool:
    """True if it was deleted. Its messages go too (ON DELETE CASCADE in the database)."""
    conversation = get_conversation(db, user_id, conversation_id)
    if conversation is None:
        return False
    db.delete(conversation)
    db.flush()
    return True


def recent_messages(db: Session, user_id: str, conversation_id: str, limit: int) -> list[Message]:
    """The last `limit` messages, oldest first: the history sent to the AI."""
    query = (
        select(Message)
        .join(Conversation)
        .where(Message.conversation_id == conversation_id, Conversation.user_id == user_id)
        .order_by(Message.position.desc())  # newest first, so LIMIT keeps the latest...
        .limit(limit)
    )
    return list(reversed(db.scalars(query).all()))  # ...then back to oldest first


def first_user_message(db: Session, user_id: str, conversation_id: str) -> Message | None:
    """The question that started the conversation (used for its title, SMA-31)."""
    query = (
        select(Message)
        .join(Conversation)
        .where(
            Message.conversation_id == conversation_id,
            Conversation.user_id == user_id,
            Message.role == "user",
        )
        .order_by(Message.position)
        .limit(1)
    )
    return db.scalar(query)


def add_message(db: Session, conversation: Conversation, **fields) -> Message:
    """Append a message at the next position.

    Takes a Conversation the caller already got with get_conversation(), so the user check
    has happened. fields: role, content, and for answers provider, model, mode, tokens...
    """
    last_position = db.scalar(
        select(func.max(Message.position)).where(Message.conversation_id == conversation.id)
    )
    message = Message(conversation_id=conversation.id, position=(last_position or 0) + 1, **fields)
    db.add(message)
    conversation.updated_at = utcnow()  # new activity: moves it to the top of the list
    db.flush()
    return message


def log_llm_calls(
    db: Session, user_id: str, conversation_id: str | None, attempts: list[Attempt], mode: str
) -> None:
    """One llm_calls row per real call to a model, failed ones included."""
    for attempt in attempts:
        db.add(
            LLMCall(
                user_id=user_id,
                conversation_id=conversation_id,
                provider=attempt.provider,
                model=attempt.model,
                mode=mode,
                status=attempt.status,
                error_type=attempt.error_type,
                fallback_used=attempt.fallback_used,
                tokens_in=attempt.tokens_in,
                tokens_out=attempt.tokens_out,
                latency_ms=attempt.latency_ms,
            )
        )
    db.flush()


# --- Study chats (SMA-49) -------------------------------------------------------------------


def with_documents(db: Session, user_id: str, conversation_id: str) -> Conversation | None:
    """One of the user's conversations, with its documents loaded (to show or change)."""
    query = (
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .options(selectinload(Conversation.documents))
    )
    return db.scalar(query)


def document_ids_of(db: Session, conversation_id: str) -> list[str]:
    """The documents a study chat may search (the caller already checked the chat's owner)."""
    query = select(conversation_documents.c.document_id).where(
        conversation_documents.c.conversation_id == conversation_id
    )
    return list(db.scalars(query))


def my_documents(db: Session, user_id: str, document_ids: list[str]) -> list[Document] | None:
    """These documents, if ALL are the user's own; None if any isn't (or doesn't exist)."""
    ids = list(dict.fromkeys(document_ids))  # no duplicates
    if not ids:
        return []
    query = select(Document).where(Document.id.in_(ids), Document.user_id == user_id)
    found = list(db.scalars(query))
    return found if len(found) == len(ids) else None
