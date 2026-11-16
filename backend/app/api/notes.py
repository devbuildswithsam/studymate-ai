"""Notes (wireframe 6.7). SMA-32.

GET/POST    /api/notes            list mine / create (optionally from a chat answer)
GET         /api/notes/search?q=  title, content or tags contain q (simple LIKE search)
GET/PATCH/DELETE /api/notes/{id}  read / edit / delete

The user comes only from get_current_user_id. Another user's note answers 404.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, StringConstraints, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.db.session import get_db
from app.models import Note
from app.repositories import notes as repo

router = APIRouter(prefix="/api/notes", tags=["notes"])

CurrentUserId = Annotated[str, Depends(get_current_user_id)]
Db = Annotated[Session, Depends(get_db)]

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Content = Annotated[str, StringConstraints(max_length=50_000)]  # kept as typed (Markdown)
Tag = Annotated[str, StringConstraints(strip_whitespace=True, max_length=30)]
Tags = Annotated[list[Tag], Field(max_length=10)]


def clean_tags(tags: list[str] | None) -> list[str] | None:
    """Drop empty tags and repeats, keeping the order."""
    if tags is None:
        return None
    return list(dict.fromkeys(tag for tag in tags if tag))


# --- Request and response shapes ---------------------------------------------------


class NoteCreate(BaseModel):
    title: Title
    content: Content = ""
    tags: Tags = []
    source_message_id: str | None = None  # the chat answer this note was saved from

    _clean_tags = field_validator("tags")(clean_tags)


class NoteUpdate(BaseModel):
    # Only the fields you send change.
    title: Title | None = None
    content: Content | None = None
    tags: Tags | None = None

    _clean_tags = field_validator("tags")(clean_tags)


class NoteSource(BaseModel):
    """Where a note was saved from: shown as "From: <chat title>"."""

    message_id: str
    conversation_id: str
    conversation_title: str | None


class NoteOut(BaseModel):
    id: str
    title: str
    content: str
    tags: list[str]
    source: NoteSource | None
    created_at: datetime
    updated_at: datetime


def note_out(note: Note) -> NoteOut:
    message = note.source_message  # loaded by the repository: no extra query
    source = None
    if message is not None:
        source = NoteSource(
            message_id=message.id,
            conversation_id=message.conversation_id,
            conversation_title=message.conversation.title,
        )
    return NoteOut(
        id=note.id,
        title=note.title,
        content=note.content,
        tags=note.tags,
        source=source,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


# --- Routes ------------------------------------------------------------------------


@router.get("", response_model=list[NoteOut])
def list_notes(user_id: CurrentUserId, db: Db) -> list[NoteOut]:
    return [note_out(n) for n in repo.list_notes(db, user_id)]


# Declared before "/{note_id}", or FastAPI would read "search" as a note id.
@router.get("/search", response_model=list[NoteOut])
def search_notes(
    q: Annotated[str, Query(min_length=1, max_length=200)], user_id: CurrentUserId, db: Db
) -> list[NoteOut]:
    text = q.strip()
    if not text:
        raise HTTPException(422, "q: search text must not be blank")
    return [note_out(n) for n in repo.search_notes(db, user_id, text)]


@router.post("", response_model=NoteOut, status_code=201)
def create_note(body: NoteCreate, user_id: CurrentUserId, db: Db) -> NoteOut:
    source = None
    if body.source_message_id:
        # Only a message from one of YOUR chats: never link to someone else's.
        source = repo.my_message(db, user_id, body.source_message_id)
        if source is None:
            raise HTTPException(404, "Message not found")
    note = repo.create_note(
        db, user_id, title=body.title, content=body.content, tags=body.tags, source_message=source
    )
    db.commit()
    return note_out(note)


@router.get("/{note_id}", response_model=NoteOut)
def get_note(note_id: str, user_id: CurrentUserId, db: Db) -> NoteOut:
    return note_out(my_note(db, user_id, note_id))


@router.patch("/{note_id}", response_model=NoteOut)
def update_note(note_id: str, body: NoteUpdate, user_id: CurrentUserId, db: Db) -> NoteOut:
    note = my_note(db, user_id, note_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(note, field, value)
    db.commit()
    return note_out(note)


@router.delete("/{note_id}", status_code=204)
def delete_note(note_id: str, user_id: CurrentUserId, db: Db) -> Response:
    if not repo.delete_note(db, user_id, note_id):
        raise HTTPException(404, "Note not found")
    db.commit()
    return Response(status_code=204)


def my_note(db: Session, user_id: str, note_id: str) -> Note:
    note = repo.get_note(db, user_id, note_id)
    if note is None:
        raise HTTPException(404, "Note not found")
    return note
