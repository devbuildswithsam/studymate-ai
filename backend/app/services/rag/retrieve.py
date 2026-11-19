"""Retrieval: find the chunks most similar to a question (guide 7.3 "Retrieval"). SMA-48.

Two steps, in this order:

1. SCOPE, in SQL: only the current user's documents, only "ready" ones, only the selected
   ones, and only vectors made by the current embedding model (same model, version and
   size: vectors from different models can't be compared, ADR-0008).
2. RANK, in NumPy: the cosine similarity of the question with every chunk left, then the
   top k.

Scope comes BEFORE ranking on purpose. Ranking everything and filtering afterwards would
let another user's better-matching chunk take a top-5 slot: at best you get fewer results,
at worst a bug in the filter leaks someone else's text. What never enters step 2 can't leak.

Cosine similarity = how closely two vectors point the same way, from -1 to 1. It compares
directions, not sizes, so a long chunk doesn't win just because its numbers are bigger.
"""

from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Document
from app.services.llm.embeddings import EmbeddingProvider

DEFAULT_TOP_K = 5  # guide 7.3: "fetch the top 5 most similar chunks"
MAX_TOP_K = 8  # guide 7.2: search_documents top_k (<= 8)


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    document_id: str
    filename: str  # for citations: "Physics.pdf, p.12"
    page: int | None  # None for TXT / MD
    text: str
    score: float  # cosine similarity, higher = closer


def retrieve(
    db: Session,
    user_id: str,
    query: str,
    provider: EmbeddingProvider,
    document_ids: list[str] | None = None,  # None = all my documents; [] = none selected
    top_k: int = DEFAULT_TOP_K,
) -> list[Hit]:
    rows = _candidates(db, user_id, provider, document_ids)  # 1. scope
    if not rows:
        return []  # nothing to search: don't spend an embedding call on the question
    question = np.asarray(provider.embed([query])[0], dtype=np.float32)
    chunks = np.frombuffer(b"".join(row.embedding for row in rows), dtype=np.float32)
    scores = cosine(chunks.reshape(len(rows), provider.dimensions), question)  # 2. rank
    best = np.argsort(-scores, kind="stable")[:top_k]  # stable: ties keep reading order
    return [
        Hit(
            chunk_id=rows[i].id,
            document_id=rows[i].document_id,
            filename=rows[i].filename,
            page=rows[i].page,
            text=rows[i].text,
            score=float(scores[i]),
        )
        for i in best
    ]


def cosine(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
    """Cosine similarity of every row of `matrix` with `vector`, all at once.

    (row . vector) / (|row| * |vector|). Gemini's vectors are already normalised (length 1,
    ADR-0008), so this is then just the dot product; dividing anyway keeps it correct for
    any model. A zero vector (no direction at all) scores 0 instead of dividing by zero.
    """
    lengths = np.linalg.norm(matrix, axis=1) * np.linalg.norm(vector)
    dots = matrix @ vector
    return np.divide(dots, lengths, out=np.zeros_like(dots), where=lengths > 0)


def _candidates(db: Session, user_id: str, provider: EmbeddingProvider, document_ids):
    query = (
        select(
            Chunk.id,
            Chunk.document_id,
            Document.filename,
            Chunk.page,
            Chunk.text,
            Chunk.embedding,
        )
        .join(Document, Chunk.document_id == Document.id)
        .where(
            Document.user_id == user_id,  # never anyone else's
            Document.status == "ready",
            Chunk.embedding.is_not(None),
            Chunk.embedding_model == provider.model,
            Chunk.embedding_version == provider.version,
            Chunk.embedding_dim == provider.dimensions,
        )
        .order_by(Document.created_at, Chunk.chunk_index)
    )
    if document_ids is not None:  # an empty list selects nothing: IN () matches no row
        query = query.where(Document.id.in_(document_ids))  # still only the user's own
    return list(db.execute(query))
