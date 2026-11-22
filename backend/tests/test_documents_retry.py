"""Retrying a document whose embedding failed (Done when, SMA-46).

The upload doesn't keep the file (SMA-44), so a retry is only possible when the chunks
exist: then it re-runs embedding, continuing where it stopped.
"""

import pytest
from sqlalchemy import select

from app.main import app
from app.models import Chunk, Document, User
from app.services.llm.embeddings import get_embedder
from app.services.llm.exceptions import LLMConfigError, RateLimitedError
from app.services.llm.fake import FakeEmbeddingProvider
from app.services.rag.embed import EmbeddingFailed, embed_document


@pytest.fixture
def local_user(client, db_session) -> User:
    return db_session.scalars(select(User)).one()


def make_document(db_session, user, chunk_count: int, status="processing") -> Document:
    document = Document(
        user_id=user.id,
        filename="Physics.pdf",
        mime_type="application/pdf",
        size_bytes=1000,
        status=status,
    )
    db_session.add(document)
    db_session.flush()
    db_session.add_all(
        Chunk(document_id=document.id, chunk_index=i, text=f"chunk {i}", token_count=2)
        for i in range(chunk_count)
    )
    db_session.commit()
    return document


def use_embedder(provider) -> None:
    app.dependency_overrides[get_embedder] = lambda: (lambda: provider)


def embedded(db_session, document) -> list[bool]:
    db_session.expire_all()
    query = select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.chunk_index)
    return [c.embedding is not None for c in db_session.scalars(query)]


# --- Done when: a simulated failure leaves the document failed, with a retry option -------------


def test_a_simulated_failure_then_a_retry(client, db_session, local_user):
    document = make_document(db_session, local_user, 120)
    failing = FakeEmbeddingProvider(
        dimensions=768, fail_on_call=2, error=RateLimitedError("quota", "fake")
    )
    with pytest.raises(EmbeddingFailed):
        embed_document(db_session, document, failing)

    shown = client.get(f"/api/documents/{document.id}").json()
    assert (shown["status"], shown["can_retry"]) == ("failed", True)
    assert "busy" in shown["error"]

    use_embedder(FakeEmbeddingProvider(dimensions=768))
    retried = client.post(f"/api/documents/{document.id}/retry")

    assert retried.status_code == 200, retried.text
    assert (retried.json()["status"], retried.json()["error"]) == ("ready", None)
    assert retried.json()["can_retry"] is False
    assert embedded(db_session, document) == [True] * 120


def test_a_retry_that_fails_again_says_why(client, db_session, local_user):
    document = make_document(db_session, local_user, 3, status="failed")
    use_embedder(FakeEmbeddingProvider(fail_on_call=1))

    retried = client.post(f"/api/documents/{document.id}/retry").json()

    assert (retried["status"], retried["can_retry"]) == ("failed", True)
    assert "Try again" in retried["error"]


def test_a_config_problem_also_fails_the_document_with_a_clear_message(
    client, db_session, local_user
):
    document = make_document(db_session, local_user, 3, status="failed")

    def no_key():
        raise LLMConfigError("GEMINI_API_KEY is not set in backend/.env", "gemini")

    app.dependency_overrides[get_embedder] = lambda: no_key
    retried = client.post(f"/api/documents/{document.id}/retry").json()

    assert retried["status"] == "failed"
    assert "GEMINI_API_KEY is not set" in retried["error"]


# --- When a retry is not possible ---------------------------------------------------------------


@pytest.mark.parametrize("status", ["processing", "ready"])
def test_only_a_failed_document_can_be_retried(client, db_session, local_user, status):
    document = make_document(db_session, local_user, 3, status=status)
    use_embedder(FakeEmbeddingProvider())

    response = client.post(f"/api/documents/{document.id}/retry")

    assert response.status_code == 409
    assert client.get(f"/api/documents/{document.id}").json()["can_retry"] is False


def test_a_document_that_failed_before_it_had_chunks_must_be_uploaded_again(
    client, db_session, local_user
):
    # e.g. "No text found" at extraction: the file wasn't kept, so there is nothing to redo.
    document = make_document(db_session, local_user, 0, status="failed")
    use_embedder(FakeEmbeddingProvider())

    response = client.post(f"/api/documents/{document.id}/retry")

    assert response.status_code == 409
    assert "upload" in response.json()["error"]["message"]
    assert client.get(f"/api/documents/{document.id}").json()["can_retry"] is False


def test_the_list_says_which_documents_can_be_retried(client, db_session, local_user):
    make_document(db_session, local_user, 2, status="failed")
    make_document(db_session, local_user, 0, status="failed")
    make_document(db_session, local_user, 2, status="ready")

    flags = sorted(d["can_retry"] for d in client.get("/api/documents").json())

    assert flags == [False, False, True]


def test_a_retry_is_ready_even_if_the_summary_then_fails(client, db_session, local_user):
    """SMA-69: the summary is a bonus; a working document must not fail because of it."""
    from app.services.llm.exceptions import ProviderUnavailableError
    from app.services.llm.fake import FakeProvider
    from app.services.llm.fallback import FallbackManager, get_fallback_manager
    from app.services.llm.registry import get_registry

    document = make_document(db_session, local_user, 3, status="failed")
    down = FakeProvider(error=ProviderUnavailableError("down", "fake"))
    manager = FallbackManager(get_registry(), lambda model: down)
    app.dependency_overrides[get_fallback_manager] = lambda: manager
    use_embedder(FakeEmbeddingProvider(dimensions=768))

    retried = client.post(f"/api/documents/{document.id}/retry").json()

    assert (retried["status"], retried["summary"]) == ("ready", None)
    assert embedded(db_session, document) == [True] * 3
