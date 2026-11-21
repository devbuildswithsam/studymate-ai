"""documents accept docx

SMA-66: documents.mime_type may also be DOCX. Written by hand (autogenerate doesn't see
CHECK constraints):
- the CHECK constraint gets the DOCX type;
- the column grows from 50 to 100 characters: the DOCX type is 71 characters long
  (SQLite doesn't enforce the length, but a future Postgres would);
- downgrade REFUSES while DOCX documents exist: the old rule would reject them, and
  deleting a student's documents silently is never an option. Delete them in the app first.

On SQLite this rebuilds the documents table. env.py switches foreign keys off during
migrations, so the DROP of the old table doesn't cascade to chunks, quizzes or decks.

Revision ID: 15dc82b50fad
Revises: 9197a9aec1fe
Create Date: 2026-11-21 19:28:18.202489

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "15dc82b50fad"
down_revision: str | Sequence[str] | None = "9197a9aec1fe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OLD_RULE = "mime_type IN ('application/pdf', 'text/plain', 'text/markdown')"
NEW_RULE = f"mime_type IN ('application/pdf', 'text/plain', 'text/markdown', '{DOCX}')"


def upgrade() -> None:
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_documents_mime_type"), type_="check")
        batch_op.alter_column(
            "mime_type",
            existing_type=sa.String(length=50),
            type_=sa.String(length=100),
            existing_nullable=False,
        )
        batch_op.create_check_constraint(batch_op.f("ck_documents_mime_type"), NEW_RULE)


def downgrade() -> None:
    docx_count = op.get_bind().execute(
        sa.text("SELECT count(*) FROM documents WHERE mime_type = :docx"), {"docx": DOCX}
    )
    if docx_count.scalar():
        raise RuntimeError(
            "Can't downgrade: some documents are DOCX files, which the older version can't "
            "store. Delete them in the app first."
        )
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_documents_mime_type"), type_="check")
        batch_op.alter_column(
            "mime_type",
            existing_type=sa.String(length=100),
            type_=sa.String(length=50),
            existing_nullable=False,
        )
        batch_op.create_check_constraint(batch_op.f("ck_documents_mime_type"), OLD_RULE)
