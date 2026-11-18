"""documents, chunks and conversation_documents (guide 7.1). SMA-44, test-first.

Runs on a temporary database built by the real migrations, so the migration is checked too.
"""

from array import array

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.models import Chunk, Conversation, Document, Task, User
from app.models.common import utcnow
from app.repositories import documents as repo


@pytest.fixture
def user(db_session) -> User:
    user = User(email="student@example.com")
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def document(db_session, user) -> Document:
    doc = Document(
        user_id=user.id, filename="Physics.pdf", mime_type="application/pdf", size_bytes=1000
    )
    db_session.add(doc)
    db_session.flush()
    return doc


def vector(dim: int) -> bytes:
    """An embedding as the database stores it: float32 numbers ("f"), 4 bytes each."""
    return array("f", range(dim)).tobytes()


def chat_with_documents(db_session, conversation_id: str) -> Conversation:
    """documents is lazy="raise" (no hidden queries): load it explicitly."""
    query = select(Conversation).where(Conversation.id == conversation_id)
    return db_session.scalar(query.options(selectinload(Conversation.documents)))


def test_a_new_document_is_processing_until_ingested(db_session, document):
    db_session.commit()
    db_session.refresh(document)

    assert document.status == "processing"
    assert (document.page_count, document.summary, document.key_points) == (None, None, None)


def test_a_chunk_stores_its_embedding_as_float32_bytes(db_session, document):
    chunk = Chunk(
        document_id=document.id,
        chunk_index=0,
        page=1,
        text="Entropy always increases.",
        token_count=5,
        embedding=vector(768),
        embedding_model="gemini-embedding-001",
        embedding_dim=768,
        embedding_version=1,
    )
    db_session.add(chunk)
    db_session.commit()

    stored = db_session.scalars(select(Chunk)).one()
    assert len(array("f", stored.embedding)) == 768


def test_a_chunk_can_wait_for_its_embedding(db_session, document):
    # Chunks are saved first, then embedded in batches (the "Embedding 18/30" progress).
    db_session.add(Chunk(document_id=document.id, chunk_index=0, text="x", token_count=1))
    db_session.commit()


def test_the_database_refuses_an_embedding_of_the_wrong_length(db_session, document):
    # Guide 7.1 vector rule: the length must equal embedding_dim, or the write fails.
    db_session.add(
        Chunk(
            document_id=document.id,
            chunk_index=0,
            text="x",
            token_count=1,
            embedding=vector(767),
            embedding_model="m",
            embedding_dim=768,
            embedding_version=1,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_an_embedding_needs_its_model_and_dimension(db_session, document):
    # Without them a vector can't be compared safely after a model change.
    db_session.add(
        Chunk(document_id=document.id, chunk_index=0, text="x", token_count=1, embedding=vector(4))
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_chunk_numbers_are_unique_within_a_document(db_session, document):
    db_session.add_all(
        [
            Chunk(document_id=document.id, chunk_index=0, text="a", token_count=1),
            Chunk(document_id=document.id, chunk_index=0, text="b", token_count=1),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize("field, value", [("status", "done"), ("mime_type", "text/html")])
def test_the_database_only_accepts_known_statuses_and_types(db_session, user, field, value):
    values = {"filename": "x", "mime_type": "text/plain", "size_bytes": 1, field: value}
    db_session.add(Document(user_id=user.id, **values))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_deleting_a_document_deletes_its_chunks_and_chat_links_but_keeps_tasks(
    db_session, user, document
):
    conversation = Conversation(user_id=user.id)
    task = Task(user_id=user.id, title="Revise Physics", document_id=document.id)
    db_session.add_all([conversation, task])
    db_session.add(Chunk(document_id=document.id, chunk_index=0, text="x", token_count=1))
    conversation.documents.append(document)
    db_session.commit()

    db_session.delete(document)
    db_session.commit()
    db_session.expire_all()

    assert db_session.scalars(select(Chunk)).all() == []
    assert chat_with_documents(db_session, conversation.id).documents == []  # link gone, chat kept
    assert db_session.get(Task, task.id).document_id is None  # the task stays, unlinked


def test_a_study_chat_links_many_documents_and_a_document_many_chats(db_session, user, document):
    other = Document(user_id=user.id, filename="DBMS.md", mime_type="text/markdown", size_bytes=10)
    first, second = Conversation(user_id=user.id), Conversation(user_id=user.id)
    first.documents.extend([document, other])
    second.documents.append(document)
    db_session.add_all([first, second])
    db_session.commit()

    db_session.expire_all()
    assert {d.filename for d in chat_with_documents(db_session, first.id).documents} == {
        "Physics.pdf",
        "DBMS.md",
    }
    assert len(chat_with_documents(db_session, second.id).documents) == 1


def test_deleting_a_user_deletes_their_documents_and_chunks(db_session, user, document):
    db_session.add(Chunk(document_id=document.id, chunk_index=0, text="x", token_count=1))
    db_session.commit()

    db_session.delete(user)
    db_session.commit()

    assert db_session.scalars(select(Document)).all() == []
    assert db_session.scalars(select(Chunk)).all() == []


def test_documents_uploaded_at_the_same_moment_list_newest_first(db_session, user):
    # Windows' clock can give two uploads the very same time: insertion order decides.
    same_time = utcnow()
    for name in ["first.txt", "second.txt", "third.txt"]:
        db_session.add(
            Document(
                user_id=user.id,
                filename=name,
                mime_type="text/plain",
                size_bytes=1,
                created_at=same_time,
            )
        )
        db_session.flush()

    names = [d.filename for d in repo.list_documents(db_session, user.id)]

    assert names == ["third.txt", "second.txt", "first.txt"]
