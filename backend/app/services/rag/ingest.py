"""The ingest pipeline with live progress (guide 7.3 steps 2-6). SMA-47.

    extract -> clean -> chunk -> save chunks -> embed -> ready

`ingest()` is a generator: it YIELDS a small event (a dict) at every step, and the upload
route streams each one to the browser as it happens ("Extracting page 12/30",
"Embedding 18/30"). Progress is real, not an animation.

Whatever happens, the document never stays "processing": a known problem (no text, the
embedding service is busy) and even a bug or a closed browser end with status "failed"
and a message. Failing after the chunks were saved leaves it retryable (SMA-46).
"""

import logging
from collections.abc import Callable, Generator, Iterator
from typing import Any

from sqlalchemy.orm import Session

from app.models import Chunk, Document
from app.services.llm.embeddings import EmbeddingProvider
from app.services.llm.exceptions import LLMConfigError
from app.services.rag.chunk import chunk_pages
from app.services.rag.clean import clean_pages
from app.services.rag.embed import EmbeddingFailed, embed_steps, failure_message
from app.services.rag.extract import NO_TEXT, ExtractionError, extract_steps

logger = logging.getLogger(__name__)

Event = dict[str, Any]  # {"stage": "embedding", "done": 18, "total": 30}
INTERRUPTED = "The upload was interrupted before it finished. Try again."
UNEXPECTED = "Something went wrong while processing this document. Try uploading it again."


def ingest(
    db: Session,
    document: Document,
    data: bytes,
    make_embedder: Callable[[], EmbeddingProvider],
) -> Iterator[Event]:
    finished = False
    try:
        yield from _steps(db, document, data, make_embedder)
        finished = True
    except Exception:  # a bug: log it for us, but never leave the document "processing"
        logger.exception("Ingesting document %s failed", document.id)
        _fail(db, document, UNEXPECTED)
        yield {"stage": "failed", "error": UNEXPECTED}
        finished = True
    finally:
        # Not finished = the browser closed the connection: the stream was stopped at one
        # of our yields (Python raises GeneratorExit there, and this block still runs).
        if not finished and document.status == "processing":
            _fail(db, document, INTERRUPTED)


def _steps(db, document, data, make_embedder) -> Generator[Event, None, None]:
    # 1. Extract, page by page.
    yield {"stage": "extracting"}
    try:
        extracted = yield from _progress("extracting", extract_steps(data, document.mime_type))
    except ExtractionError as e:
        yield _fail(db, document, str(e))
        return
    document.page_count = extracted.page_count

    # 2-3. Clean and chunk (fast: one event), then save the chunks.
    yield {"stage": "chunking"}
    chunks = chunk_pages(clean_pages(extracted.pages, document.mime_type))
    if not chunks:  # cleaning removed everything (only headers and page numbers)
        yield _fail(db, document, NO_TEXT)
        return
    db.add_all(
        Chunk(
            document_id=document.id,
            chunk_index=c.index,
            page=c.page,
            text=c.text,
            token_count=c.token_count,
        )
        for c in chunks
    )
    db.commit()  # saved before embedding: if embedding fails, a retry can finish it

    # 4. Embed, batch by batch.
    yield {"stage": "embedding", "done": 0, "total": len(chunks)}
    try:
        provider = make_embedder()
        yield from _progress("embedding", embed_steps(db, document, provider))
    except LLMConfigError as e:  # e.g. no API key: building the provider failed
        yield _fail(db, document, failure_message(e))
        return
    except EmbeddingFailed:
        yield {"stage": "failed", "error": document.error}  # embed_steps marked it failed
        return

    # 5. Done. (SMA-50 adds the summary and key points here.)
    document.status = "ready"
    db.commit()
    yield {"stage": "ready"}


def _progress(stage: str, steps: Generator[tuple[int, int], None, Any]):
    """Turn a step's (done, total) tuples into events, and return the step's result."""
    while True:
        try:
            done, total = next(steps)
        except StopIteration as finished:
            return finished.value
        yield {"stage": stage, "done": done, "total": total}


def _fail(db: Session, document: Document, message: str) -> Event:
    db.rollback()  # whatever was half-done in this transaction
    document.status = "failed"
    document.error = message
    db.commit()
    return {"stage": "failed", "error": message}
