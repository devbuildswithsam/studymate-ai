"""Documents: the user's uploads. SMA-44.

Every lookup takes user_id: another user's document is "not found", like one that never
existed (the isolation rule, SMA-34).
"""

from sqlalchemy import literal_column, select
from sqlalchemy.orm import Session

from app.models import Chunk, Document


def create_document(
    db: Session, user_id: str, *, filename: str, mime_type: str, size_bytes: int
) -> Document:
    document = Document(
        user_id=user_id, filename=filename, mime_type=mime_type, size_bytes=size_bytes
    )
    db.add(document)
    db.flush()  # get the id and defaults now
    return document


def list_documents(db: Session, user_id: str) -> list[Document]:
    # Newest first. Windows' clock can give two uploads the very same time, so SQLite's
    # rowid (the insertion order, not a mapped column) breaks ties.
    rowid = literal_column("documents.rowid")
    query = select(Document).where(Document.user_id == user_id)
    return list(db.scalars(query.order_by(Document.created_at.desc(), rowid.desc())))


def get_document(db: Session, user_id: str, document_id: str) -> Document | None:
    return db.scalar(
        select(Document).where(Document.id == document_id, Document.user_id == user_id)
    )


def delete_document(db: Session, user_id: str, document_id: str) -> bool:
    """Its chunks and chat links go too (ON DELETE CASCADE); tasks keep, unlinked."""
    document = get_document(db, user_id, document_id)
    if document is None:
        return False
    db.delete(document)
    db.flush()
    return True


def ids_with_chunks(db: Session, document_ids: list[str]) -> set[str]:
    """Which of these documents have chunks (one query for a whole list, no N+1)."""
    if not document_ids:
        return set()
    query = select(Chunk.document_id).where(Chunk.document_id.in_(document_ids)).distinct()
    return set(db.scalars(query))
