"""Embedding a document's chunks (guide 7.3 step 5). SMA-46, test-first.

Done when: a document's chunks all have vectors of the right dimension, and a simulated
failure leaves the document in `failed` with a retry option.
"""

from array import array

import pytest
from sqlalchemy import select

from app.models import Chunk, Document, User
from app.services.llm.embeddings import EmbeddingError
from app.services.llm.exceptions import (
    LLMConfigError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.services.llm.fake import FakeEmbeddingProvider
from app.services.rag.embed import EmbeddingFailed, embed_document


@pytest.fixture
def user(db_session) -> User:
    user = User(email="student@example.com")
    db_session.add(user)
    db_session.commit()
    return user


def make_document(db_session, user, chunk_count: int, name="Physics.pdf") -> Document:
    document = Document(
        user_id=user.id, filename=name, mime_type="application/pdf", size_bytes=1000
    )
    db_session.add(document)
    db_session.flush()
    db_session.add_all(
        Chunk(
            document_id=document.id, chunk_index=i, page=1, text=f"{name} chunk {i}", token_count=3
        )
        for i in range(chunk_count)
    )
    db_session.commit()
    return document


def chunks_of(db_session, document) -> list[Chunk]:
    db_session.expire_all()
    query = select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.chunk_index)
    return list(db_session.scalars(query))


# --- Done when: every chunk gets a vector of the right dimension -------------------------------


def test_every_chunk_gets_a_float32_vector_of_the_right_dimension(db_session, user):
    document = make_document(db_session, user, 120)
    provider = FakeEmbeddingProvider(dimensions=768, batch_size=50)

    embed_document(db_session, document, provider)

    chunks = chunks_of(db_session, document)
    assert all(len(array("f", c.embedding)) == 768 for c in chunks)
    assert {(c.embedding_model, c.embedding_dim, c.embedding_version) for c in chunks} == {
        ("fake-embedding", 768, 1)
    }


def test_chunks_are_embedded_in_batches_in_reading_order(db_session, user):
    document = make_document(db_session, user, 120)
    provider = FakeEmbeddingProvider(batch_size=50)

    embed_document(db_session, document, provider)

    assert [len(b) for b in provider.batches] == [50, 50, 20]
    assert provider.batches[0][:2] == ["Physics.pdf chunk 0", "Physics.pdf chunk 1"]


def test_each_vector_belongs_to_its_own_chunk(db_session, user):
    document = make_document(db_session, user, 3)
    provider = FakeEmbeddingProvider()

    embed_document(db_session, document, provider)

    for chunk in chunks_of(db_session, document):
        assert array("f", chunk.embedding) == provider.embed([chunk.text])[0]


def test_progress_is_reported_after_each_batch(db_session, user):
    document = make_document(db_session, user, 120)
    progress = []

    embed_document(db_session, document, FakeEmbeddingProvider(batch_size=50), progress.append)

    assert progress == [(50, 120), (100, 120), (120, 120)]  # "Embedding 50/120" for SMA-47


def test_only_this_documents_chunks_are_embedded(db_session, user):
    document = make_document(db_session, user, 2)
    other = make_document(db_session, user, 2, name="Other.pdf")

    embed_document(db_session, document, FakeEmbeddingProvider())

    assert all(c.embedding is None for c in chunks_of(db_session, other))


# --- Done when: a failure leaves the document failed, with a retry option -----------------------


def test_a_failure_marks_the_document_failed_and_keeps_finished_batches(db_session, user):
    document = make_document(db_session, user, 120)
    provider = FakeEmbeddingProvider(
        batch_size=50, fail_on_call=2, error=ProviderUnavailableError("down", "fake")
    )

    with pytest.raises(EmbeddingFailed):
        embed_document(db_session, document, provider)

    db_session.refresh(document)
    assert document.status == "failed"
    assert "Try again" in document.error
    embedded = [c.embedding is not None for c in chunks_of(db_session, document)]
    assert embedded == [True] * 50 + [False] * 70  # the first batch was saved


def test_a_retry_continues_where_it_stopped(db_session, user):
    document = make_document(db_session, user, 120)
    failing = FakeEmbeddingProvider(batch_size=50, fail_on_call=2)
    with pytest.raises(EmbeddingFailed):
        embed_document(db_session, document, failing)

    working = FakeEmbeddingProvider(batch_size=50)
    embed_document(db_session, document, working)

    assert [len(b) for b in working.batches] == [50, 20]  # only what was missing
    assert all(c.embedding is not None for c in chunks_of(db_session, document))


@pytest.mark.parametrize(
    "error, message",
    [
        (RateLimitedError("quota", "fake"), "busy"),  # free-tier limit
        (ProviderUnavailableError("503", "fake"), "didn't answer"),
        (LLMConfigError("GEMINI_API_KEY is not set in backend/.env", "fake"), "set up"),
        (EmbeddingError("3 numbers instead of 4", "fake"), "unexpected"),
    ],
)
def test_the_failure_message_says_what_to_do(db_session, user, error, message):
    document = make_document(db_session, user, 1)

    with pytest.raises(EmbeddingFailed):
        embed_document(db_session, document, FakeEmbeddingProvider(fail_on_call=1, error=error))

    db_session.refresh(document)
    assert message in document.error


def test_vectors_of_the_wrong_size_are_never_stored(db_session, user):
    document = make_document(db_session, user, 3)
    provider = FakeEmbeddingProvider(dimensions=768, wrong_dimensions=767)

    with pytest.raises(EmbeddingFailed):
        embed_document(db_session, document, provider)

    assert all(c.embedding is None for c in chunks_of(db_session, document))


# --- Never two embedding models in one document --------------------------------------------------


@pytest.mark.parametrize(
    "old",
    [
        {"model": "old-model"},  # the model changed
        {"version": 2},  # models.yaml bumped the version
        {"dimensions": 4},  # the size changed
    ],
)
def test_vectors_from_another_model_or_version_are_redone(db_session, user, old):
    # The old vectors differ from the current provider in exactly ONE way each time.
    current_settings = {"model": "fake-embedding", "dimensions": 8, "version": 1}
    document = make_document(db_session, user, 4)
    embed_document(db_session, document, FakeEmbeddingProvider(**{**current_settings, **old}))
    current = FakeEmbeddingProvider(**current_settings)

    embed_document(db_session, document, current)

    chunks = chunks_of(db_session, document)
    assert {(c.embedding_model, c.embedding_dim, c.embedding_version) for c in chunks} == {
        ("fake-embedding", 8, 1)
    }
    assert sum(len(b) for b in current.batches) == 4  # every chunk re-embedded


def test_a_fully_embedded_document_needs_no_calls(db_session, user):
    document = make_document(db_session, user, 3)
    embed_document(db_session, document, FakeEmbeddingProvider())
    again = FakeEmbeddingProvider()

    embed_document(db_session, document, again)

    assert again.batches == []
