"""The ingest pipeline: extract -> clean -> chunk -> save -> embed, with progress events.
SMA-47, test-first. Real PDFs (tests/pdf_maker.py), fake embeddings.
"""

import json
import textwrap

import pytest
from sqlalchemy import select

from app.models import Chunk, Document, User
from app.services.llm.exceptions import LLMConfigError, RateLimitedError
from app.services.llm.fake import FakeEmbeddingProvider
from app.services.rag.ingest import ingest
from tests.pdf_maker import make_pdf


@pytest.fixture
def user(db_session) -> User:
    user = User(email="student@example.com")
    db_session.add(user)
    db_session.commit()
    return user


def new_document(db_session, user, mime_type="application/pdf") -> Document:
    document = Document(user_id=user.id, filename="notes", mime_type=mime_type, size_bytes=1)
    db_session.add(document)
    db_session.commit()
    return document


def lecture(pages: int) -> bytes:
    # Short lines, like a real page (layout mode ignores text running off the page).
    text = "\n".join(textwrap.wrap("Heat flows from hot to cold, and entropy rises. " * 40, 70))
    return make_pdf([f"Page {n} topic.\n\n{text}" for n in range(1, pages + 1)])


def run(db_session, document, data, embedder) -> list[dict]:
    return list(ingest(db_session, document, data, lambda: embedder))


def chunks_of(db_session, document) -> list[Chunk]:
    db_session.expire_all()
    return list(db_session.scalars(select(Chunk).where(Chunk.document_id == document.id)))


# --- Done when: a 30-page PDF goes through to Ready, with real progress ---------------------------


def test_a_30_page_pdf_reports_each_step_through_to_ready(db_session, user):
    document = new_document(db_session, user)

    events = run(db_session, document, lecture(30), FakeEmbeddingProvider(batch_size=10))

    stages = [e["stage"] for e in events]
    pages = [(e["done"], e["total"]) for e in events if e["stage"] == "extracting" and "done" in e]
    assert pages == [(n, 30) for n in range(1, 31)]  # extracting page 1/30 ... 30/30
    embedding = [(e["done"], e["total"]) for e in events if e["stage"] == "embedding"]
    total = embedding[0][1]
    assert embedding[0] == (0, total) and embedding[-1] == (total, total)
    assert [d for d, _ in embedding] == sorted(d for d, _ in embedding)  # only goes up
    assert stages.index("chunking") < stages.index("embedding") < stages.index("ready")
    assert stages[-1] == "ready"


def test_a_ready_document_has_its_pages_and_embedded_chunks(db_session, user):
    document = new_document(db_session, user)

    run(db_session, document, lecture(30), FakeEmbeddingProvider())

    db_session.refresh(document)
    assert (document.status, document.page_count, document.error) == ("ready", 30, None)
    chunks = chunks_of(db_session, document)
    assert len(chunks) >= 20
    assert all(c.embedding is not None for c in chunks)
    assert {c.page for c in chunks} <= set(range(1, 31))


def test_a_text_file_has_no_page_progress(db_session, user):
    document = new_document(db_session, user, "text/markdown")
    data = (
        "# Thermodynamics\n\n" + "Entropy always increases in an isolated system. " * 20
    ).encode()

    events = run(db_session, document, data, FakeEmbeddingProvider())

    assert [e["stage"] for e in events] == [
        "extracting",
        "chunking",
        "embedding",
        "embedding",
        "ready",
    ]
    db_session.refresh(document)
    assert (document.status, document.page_count) == ("ready", None)


def test_every_event_can_be_sent_as_json(db_session, user):
    document = new_document(db_session, user)

    for event in run(db_session, document, lecture(2), FakeEmbeddingProvider()):
        json.dumps(event)


# --- When it stops -------------------------------------------------------------------------------


def test_a_scanned_pdf_fails_with_no_text_found_and_cannot_be_retried(db_session, user):
    document = new_document(db_session, user)

    events = run(db_session, document, make_pdf([None, None, None]), FakeEmbeddingProvider())

    assert events[-1]["stage"] == "failed"
    assert "No text found" in events[-1]["error"]
    db_session.refresh(document)
    assert document.status == "failed"
    assert chunks_of(db_session, document) == []  # nothing to retry: upload again


def test_an_embedding_failure_keeps_the_chunks_so_it_can_be_retried(db_session, user):
    document = new_document(db_session, user)
    failing = FakeEmbeddingProvider(
        batch_size=5, fail_on_call=2, error=RateLimitedError("quota", "fake")
    )

    events = run(db_session, document, lecture(30), failing)

    assert events[-1] == {"stage": "failed", "error": events[-1]["error"]}
    assert "busy" in events[-1]["error"]
    chunks = chunks_of(db_session, document)
    assert sum(c.embedding is not None for c in chunks) == 5  # the first batch was kept


def test_missing_embedding_config_fails_the_document_not_the_request(db_session, user):
    document = new_document(db_session, user)

    def no_key():
        raise LLMConfigError("GEMINI_API_KEY is not set in backend/.env", "gemini")

    events = list(ingest(db_session, document, lecture(2), no_key))

    assert events[-1]["stage"] == "failed"
    assert "GEMINI_API_KEY is not set" in events[-1]["error"]
    assert chunks_of(db_session, document)  # chunks saved: a retry can finish it


def test_an_unexpected_bug_still_ends_with_a_failed_document(db_session, user):
    document = new_document(db_session, user)

    class Broken(FakeEmbeddingProvider):
        def _embed(self, texts):
            raise ZeroDivisionError("a bug in our code")

    events = run(db_session, document, lecture(2), Broken())

    assert events[-1]["stage"] == "failed"
    assert "Something went wrong" in events[-1]["error"]
    db_session.refresh(document)
    assert document.status == "failed"  # never stuck on "processing"


def test_a_closed_connection_marks_the_document_failed(db_session, user):
    # The browser went away: Starlette closes the generator at its next yield.
    document = new_document(db_session, user)
    events = ingest(db_session, document, lecture(30), lambda: FakeEmbeddingProvider())
    next(events)
    next(events)

    events.close()

    db_session.refresh(document)
    assert document.status == "failed"
    assert "interrupted" in document.error
