"""Step 5 of ingestion: give every chunk its vector (guide 7.3). SMA-46.

- Batches of `batch_size` texts (Gemini takes at most 100 per request).
- Each batch is committed as soon as it's done: if a later batch fails, the finished ones
  are kept, and a retry only embeds what is still missing.
- Never two models in one document: vectors made by another model, version or size are
  cleared first, then redone. Search can only compare vectors from the same model.
- On failure the document becomes "failed" with a message saying what to do, and
  EmbeddingFailed is raised. There is no fallback to another embedding model (guide 7.5).
- Only provider failures (LLMError: the adapters translate every API error) mark the
  document failed. Anything else is a bug in our code: it is raised, not hidden.
"""

from collections.abc import Callable

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.models import Chunk, Document
from app.services.llm.embeddings import EmbeddingError, EmbeddingProvider
from app.services.llm.exceptions import (
    LLMConfigError,
    LLMError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitedError,
)

Progress = Callable[[tuple[int, int]], None]  # (chunks done, chunks in total)


class EmbeddingFailed(Exception):
    """Embedding stopped; the document is marked failed and can be retried."""


def embed_document(
    db: Session,
    document: Document,
    provider: EmbeddingProvider,
    on_progress: Progress | None = None,
) -> None:
    _clear_vectors_from_other_models(db, document, provider)
    todo = list(
        db.scalars(
            select(Chunk)
            .where(Chunk.document_id == document.id, Chunk.embedding.is_(None))
            .order_by(Chunk.chunk_index)
        )
    )
    total = db.query(Chunk).filter(Chunk.document_id == document.id).count()
    done = total - len(todo)
    for start in range(0, len(todo), provider.batch_size):
        batch = todo[start : start + provider.batch_size]
        try:
            vectors = provider.embed([chunk.text for chunk in batch])
        except LLMError as e:
            db.rollback()
            document.status = "failed"
            document.error = failure_message(e)
            db.commit()
            raise EmbeddingFailed(document.error) from e
        for chunk, vector in zip(batch, vectors, strict=True):
            chunk.embedding = vector.tobytes()  # float32: 4 bytes per number
            chunk.embedding_model = provider.model
            chunk.embedding_dim = provider.dimensions
            chunk.embedding_version = provider.version
        db.commit()  # keep this batch, whatever happens to the next one
        done += len(batch)
        if on_progress:
            on_progress((done, total))


def _clear_vectors_from_other_models(db: Session, document: Document, provider) -> None:
    db.execute(
        update(Chunk)
        .where(
            Chunk.document_id == document.id,
            Chunk.embedding.is_not(None),
            or_(
                Chunk.embedding_model != provider.model,
                Chunk.embedding_version != provider.version,
                Chunk.embedding_dim != provider.dimensions,
            ),
        )
        .values(embedding=None, embedding_model=None, embedding_dim=None, embedding_version=None)
    )
    db.commit()


def failure_message(error: LLMError) -> str:
    """What the student sees on the document: what happened, and what to do next."""
    if isinstance(error, RateLimitedError):
        return "The embedding service is busy (free-tier limit). Wait a minute, then try again."
    if isinstance(error, ProviderUnavailableError | ProviderTimeoutError):
        return "The embedding service didn't answer. Try again in a moment."
    if isinstance(error, LLMConfigError):
        return f"Embeddings aren't set up correctly ({error}). Fix it, then try again."
    if isinstance(error, EmbeddingError):
        return f"The embedding service sent unexpected vectors ({error}). Try again."
    return f"Embedding failed ({error}). Try again."
