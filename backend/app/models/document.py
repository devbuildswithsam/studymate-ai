"""documents, chunks and conversation_documents (guide 7.1, 7.3). SMA-44.

A document is the RECORD of an upload: its name, type, size and status. The file itself is
never stored (guide 9: "text-only storage"); its text lives in chunks, ready to search.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import allowed, new_id, utcnow

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCUMENT_TYPES = ("application/pdf", "text/plain", "text/markdown", DOCX_TYPE)  # SMA-66: DOCX
DOCUMENT_STATUSES = ("processing", "ready", "failed")
FLOAT32_BYTES = 4  # one number of an embedding

# Many-to-many: which documents a study chat may search (guide 7.1). Only two foreign
# keys, no data of its own, so a plain Table instead of a model class.
conversation_documents = Table(
    "conversation_documents",
    Base.metadata,
    Column(
        "conversation_id",
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # Indexed: "which chats use this document?" (the primary key only helps
    # lookups that start with conversation_id).
    Column(
        "document_id",
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(allowed("mime_type", DOCUMENT_TYPES), name="mime_type"),
        CheckConstraint(allowed("status", DOCUMENT_STATUSES), name="status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))  # shown in the UI, never used as a path
    mime_type: Mapped[str] = mapped_column(String(100))  # decided by the content, not the name
    size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)  # PDFs only, known after extraction
    status: Mapped[str] = mapped_column(
        String(12), default="processing", server_default="processing"
    )
    error: Mapped[str | None] = mapped_column(Text)  # why it failed, e.g. "no text found"
    summary: Mapped[str | None] = mapped_column(Text)  # SMA-50
    key_points: Mapped[list[Any] | None] = mapped_column(JSON)  # SMA-50
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Chunk(Base):
    """A piece of a document's text, with its embedding (the vector search compares)."""

    __tablename__ = "chunks"
    __table_args__ = (
        # One number per position. Its index also serves "this document's chunks".
        UniqueConstraint("document_id", "chunk_index"),
        # Guide 7.1 vector rule, enforced by the DATABASE: a vector must say which model
        # made it, and be exactly embedding_dim float32 numbers long, or the write fails.
        CheckConstraint(
            "embedding IS NULL OR ("
            "embedding_model IS NOT NULL AND embedding_version IS NOT NULL"
            f" AND length(embedding) = embedding_dim * {FLOAT32_BYTES})",
            name="embedding_matches_dim",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # No user_id: a chunk belongs to a document, and the document to a user. Every
    # search joins documents and filters on documents.user_id (SMA-48).
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)  # 0, 1, 2... in reading order
    page: Mapped[int | None] = mapped_column(Integer)  # for citations; DOCX: the section (SMA-66)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    # NULL until embedded (chunks are saved first, then embedded in batches).
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    embedding_dim: Mapped[int | None] = mapped_column(Integer)
    embedding_version: Mapped[int | None] = mapped_column(Integer)  # bump to re-embed safely
