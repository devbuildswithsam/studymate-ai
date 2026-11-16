"""Notes: the user's own notes, optionally saved from a chat answer. SMA-32.

Every lookup takes user_id. Notes are returned with their source message and its chat
already loaded, so showing "From: <chat title>" never runs one query per note (N+1).
"""

from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Conversation, Message, Note

# Load each note's source message, then those messages' chats: 2 extra queries in total.
WITH_SOURCE = selectinload(Note.source_message).selectinload(Message.conversation)


def list_notes(db: Session, user_id: str) -> list[Note]:
    """The user's notes, most recently edited first."""
    query = (
        select(Note)
        .where(Note.user_id == user_id)
        .options(WITH_SOURCE)
        .order_by(Note.updated_at.desc())
    )
    return list(db.scalars(query))


def search_notes(db: Session, user_id: str, text: str, limit: int = 50) -> list[Note]:
    """Notes whose title, content or tags contain `text`, ignoring case."""
    pattern = like_pattern(text)
    query = (
        select(Note)
        .where(
            Note.user_id == user_id,
            or_(
                Note.title.ilike(pattern, escape="\\"),
                Note.content.ilike(pattern, escape="\\"),
                # tags is a JSON list, stored as text like '["physics", "exam"]'
                cast(Note.tags, String).ilike(pattern, escape="\\"),
            ),
        )
        .options(WITH_SOURCE)
        .order_by(Note.updated_at.desc())
        .limit(limit)
    )
    return list(db.scalars(query))


def like_pattern(text: str) -> str:
    """'%text%' with LIKE's wildcards escaped, so they're searched literally.

    In LIKE, % means "any text" and _ means "any one character": unescaped, a search
    for "%" would match every note.
    """
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def get_note(db: Session, user_id: str, note_id: str) -> Note | None:
    query = select(Note).where(Note.id == note_id, Note.user_id == user_id).options(WITH_SOURCE)
    return db.scalar(query)


def create_note(
    db: Session,
    user_id: str,
    *,
    title: str,
    content: str,
    tags: list[str],
    source_message: Message | None = None,
) -> Note:
    note = Note(
        user_id=user_id, title=title, content=content, tags=tags, source_message=source_message
    )
    db.add(note)
    db.flush()
    return note


def delete_note(db: Session, user_id: str, note_id: str) -> bool:
    note = get_note(db, user_id, note_id)
    if note is None:
        return False
    db.delete(note)
    db.flush()
    return True


def my_message(db: Session, user_id: str, message_id: str) -> Message | None:
    """A message from one of the user's own chats, or None (also when it's someone else's)."""
    query = (
        select(Message)
        .join(Conversation)
        .where(Message.id == message_id, Conversation.user_id == user_id)
        .options(selectinload(Message.conversation))
    )
    return db.scalar(query)
