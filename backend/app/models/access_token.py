"""access_tokens: personal access tokens for MCP clients (guide 7.2). SMA-61.

The token itself is never stored: only its SHA-256 hash. Someone who reads the database
(a backup, a leak) can't use the hashes to call /mcp. A random 32-byte token can't be
guessed, so a fast hash is enough; human passwords need a slow one (Argon2, ADR-0009).
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import new_id, utcnow


class AccessToken(Base):
    __tablename__ = "access_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))  # e.g. "MCP Inspector on my laptop"
    # sha256 hex of the token: 64 characters. Unique and indexed: /mcp looks it up by hash.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(12))  # "smat_AbCdEfG": to recognise it in the list
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
