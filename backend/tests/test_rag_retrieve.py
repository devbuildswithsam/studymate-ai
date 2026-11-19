"""Retrieval: the chunks most similar to a question (guide 7.3 "Retrieval"). SMA-48, test-first.

Done when: retrieval tests pass, including one proving user B's chunks are never returned.

The embedder here is a tiny keyword model: each dimension counts one topic word, so a
chunk about entropy really is closest to a question about entropy. Real meaning-based
vectors behave the same way, just in 768 dimensions.
"""

import pytest

from app.models import Chunk, Document, User
from app.services.llm.embeddings import EmbeddingProvider
from app.services.llm.registry import EmbeddingConfig
from app.services.rag.retrieve import DEFAULT_TOP_K, retrieve

TOPICS = ["entropy", "heat", "work", "engine", "photosynthesis", "cell"]


class KeywordEmbedder(EmbeddingProvider):
    def __init__(self, model="keyword-model", version=1):
        super().__init__(
            EmbeddingConfig(
                id=model, provider="fake", dimensions=len(TOPICS), version=version, batch_size=50
            )
        )
        self.queries: list[str] = []

    def _embed(self, texts):
        self.queries.extend(texts)
        return [[float(text.lower().count(word)) for word in TOPICS] for text in texts]


@pytest.fixture
def embedder() -> KeywordEmbedder:
    return KeywordEmbedder()


@pytest.fixture
def alice(db_session) -> User:
    return make_user(db_session, "alice@example.com")


@pytest.fixture
def bob(db_session) -> User:
    return make_user(db_session, "bob@example.com")


def make_user(db_session, email) -> User:
    user = User(email=email)
    db_session.add(user)
    db_session.commit()
    return user


def add_document(db_session, user, filename, chunks, embedder, status="ready") -> Document:
    """A document whose chunks (page, text) are already embedded by `embedder`."""
    document = Document(
        user_id=user.id, filename=filename, mime_type="application/pdf", size_bytes=1, status=status
    )
    db_session.add(document)
    db_session.flush()
    vectors = embedder.embed([text for _, text in chunks]) if embedder else [None] * len(chunks)
    for index, ((page, text), vector) in enumerate(zip(chunks, vectors, strict=True)):
        db_session.add(
            Chunk(
                document_id=document.id,
                chunk_index=index,
                page=page,
                text=text,
                token_count=5,
                embedding=vector.tobytes() if vector is not None else None,
                embedding_model=embedder.model if embedder else None,
                embedding_dim=embedder.dimensions if embedder else None,
                embedding_version=embedder.version if embedder else None,
            )
        )
    db_session.commit()
    return document


PHYSICS = [
    (1, "Heat flows from hot to cold."),
    (2, "Entropy always increases. Entropy measures disorder."),
    (3, "Work done by an engine."),
    (4, "A heat engine turns heat into work."),
    (5, "Entropy and heat: the second law."),
    (6, "Photosynthesis happens in a cell."),
    (7, "Nothing about the topics at all."),
]


def search(db_session, user, query, embedder, **kwargs):
    return retrieve(db_session, user.id, query, embedder, **kwargs)


# --- Ranking ---------------------------------------------------------------------------------------


def test_the_best_matches_come_first_with_document_name_and_page(db_session, alice, embedder):
    add_document(db_session, alice, "Physics.pdf", PHYSICS, embedder)

    hits = search(db_session, alice, "What is entropy?", embedder)

    assert (hits[0].filename, hits[0].page) == ("Physics.pdf", 2)  # "Entropy ... Entropy"
    assert hits[0].text.startswith("Entropy always increases")
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert embedder.queries[-1] == "What is entropy?"  # the question itself was embedded


def test_it_returns_the_top_5_by_default(db_session, alice, embedder):
    add_document(db_session, alice, "Physics.pdf", PHYSICS, embedder)

    assert DEFAULT_TOP_K == 5
    assert len(search(db_session, alice, "heat entropy work engine cell", embedder)) == 5


def test_top_k_can_ask_for_fewer_or_more(db_session, alice, embedder):
    add_document(db_session, alice, "Physics.pdf", PHYSICS, embedder)

    assert len(search(db_session, alice, "heat", embedder, top_k=2)) == 2
    assert len(search(db_session, alice, "heat", embedder, top_k=8)) == len(PHYSICS)  # all 7


def test_similarity_is_cosine_not_just_size(db_session, alice):
    # A long chunk repeating many topic words has big numbers, but points the wrong way.
    # Cosine compares DIRECTIONS, so the short, on-topic chunk still wins.
    embedder = KeywordEmbedder()
    add_document(
        db_session,
        alice,
        "Notes.md",
        # Dot products: 1 for "entropy", 2 for the long one (it says entropy twice), so a plain
        # dot product would rank the long one first. Cosine: 1.0 vs 0.33.
        [(None, "entropy"), (None, "heat heat heat heat work work work work entropy entropy")],
        embedder,
    )

    best = search(db_session, alice, "entropy", embedder)[0]

    assert best.text == "entropy"
    assert best.score == pytest.approx(1.0)


def test_text_files_have_no_page(db_session, alice, embedder):
    add_document(db_session, alice, "notes.md", [(None, "Entropy rises.")], embedder)

    assert search(db_session, alice, "entropy", embedder)[0].page is None


# --- Scope: filtered BEFORE ranking --------------------------------------------------------------


def test_done_when_user_b_s_chunks_are_never_returned(db_session, alice, bob, embedder):
    # Bob's chunk matches the question perfectly; Alice's only partly. Ranking first and
    # filtering later could leak it (or leave Alice with fewer results). Filtering first can't.
    add_document(db_session, bob, "Bob's secrets.pdf", [(1, "entropy entropy entropy")], embedder)
    add_document(db_session, alice, "Physics.pdf", PHYSICS, embedder)

    hits = search(db_session, alice, "entropy", embedder)

    assert all(h.filename == "Physics.pdf" for h in hits)
    assert len(hits) == 5  # Alice still gets her full top 5


def test_b_s_document_ids_are_ignored_even_when_asked_for(db_session, alice, bob, embedder):
    bobs = add_document(db_session, bob, "Bob's.pdf", [(1, "entropy")], embedder)
    alices = add_document(db_session, alice, "Physics.pdf", PHYSICS, embedder)

    hits = search(db_session, alice, "entropy", embedder, document_ids=[bobs.id, alices.id])

    assert {h.document_id for h in hits} == {alices.id}
    assert search(db_session, alice, "entropy", embedder, document_ids=[bobs.id]) == []


def test_only_the_selected_documents_are_searched(db_session, alice, embedder):
    physics = add_document(db_session, alice, "Physics.pdf", PHYSICS, embedder)
    add_document(db_session, alice, "Biology.pdf", [(1, "entropy in a cell")], embedder)

    hits = search(db_session, alice, "entropy", embedder, document_ids=[physics.id])

    assert {h.filename for h in hits} == {"Physics.pdf"}


def test_no_selected_documents_means_no_results(db_session, alice, embedder):
    add_document(db_session, alice, "Physics.pdf", PHYSICS, embedder)

    assert search(db_session, alice, "entropy", embedder, document_ids=[]) == []


@pytest.mark.parametrize("status", ["processing", "failed"])
def test_documents_that_are_not_ready_are_not_searched(db_session, alice, embedder, status):
    add_document(db_session, alice, "Half.pdf", [(1, "entropy")], embedder, status=status)

    assert search(db_session, alice, "entropy", embedder) == []


def test_vectors_from_another_model_or_version_are_never_compared(db_session, alice, embedder):
    add_document(db_session, alice, "Old.pdf", [(1, "entropy")], KeywordEmbedder(model="old"))
    add_document(db_session, alice, "Older.pdf", [(1, "entropy")], KeywordEmbedder(version=2))
    add_document(db_session, alice, "Not yet.pdf", [(1, "entropy")], None)  # no vector at all
    add_document(db_session, alice, "Current.pdf", [(1, "heat")], embedder)

    assert {h.filename for h in search(db_session, alice, "entropy", embedder)} == {"Current.pdf"}


def test_vectors_of_another_size_are_never_compared(db_session, alice, embedder):
    # Same model name and version, different size: comparing would crash (or mislead).
    class FourTopics(KeywordEmbedder):
        def __init__(self):
            super().__init__()
            self.dimensions = 4

        def _embed(self, texts):
            return [vector[:4] for vector in super()._embed(texts)]

    add_document(db_session, alice, "Small.pdf", [(1, "entropy")], FourTopics())
    add_document(db_session, alice, "Current.pdf", [(1, "heat")], embedder)

    assert {h.filename for h in search(db_session, alice, "entropy", embedder)} == {"Current.pdf"}


def test_a_chunk_whose_vector_was_cleared_is_skipped(db_session, alice, embedder):
    document = add_document(
        db_session, alice, "Physics.pdf", [(1, "entropy"), (2, "heat")], embedder
    )
    cleared = document_chunks(db_session, document)[0]
    cleared.embedding = None  # e.g. halfway through a re-embed; the labels are still there
    db_session.commit()

    assert [h.page for h in search(db_session, alice, "entropy", embedder)] == [2]


def document_chunks(db_session, document) -> list[Chunk]:
    from sqlalchemy import select

    query = select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.chunk_index)
    return list(db_session.scalars(query))


def test_no_documents_means_no_results(db_session, alice, embedder):
    assert search(db_session, alice, "entropy", embedder) == []
