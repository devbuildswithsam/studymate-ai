"""Notes API: CRUD, search, and notes saved from a chat answer. SMA-32, written test-first.

Every note belongs to one user: another user's note answers 404, like one that doesn't exist.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import event, select

from app.api.deps import get_current_user_id
from app.main import app
from app.models import Conversation, Message, Note, User
from app.repositories import notes as repo
from app.services.llm.fake import FakeProvider
from tests.test_conversations_api import new_conversation, send, use_fakes  # noqa: F401


@pytest.fixture
def notes_client(client):
    """The test client on a seeded temporary database, with a fake AI for chat."""
    use_fakes({"main": FakeProvider(replies=["F = m * a."]), "backup": FakeProvider()})
    return client


def create(client, **body):
    response = client.post("/api/notes", json={"title": "A note", "content": "", **body})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def bob(db_session) -> User:
    user = User(email="bob@example.com")
    db_session.add(user)
    db_session.commit()
    return user


# --- CRUD --------------------------------------------------------------------------


def test_create_and_get_a_note(notes_client):
    created = create(notes_client, title="Newton's 2nd law", content="F = m * a", tags=["physics"])

    note = notes_client.get(f"/api/notes/{created['id']}").json()

    assert (note["title"], note["content"], note["tags"]) == (
        "Newton's 2nd law",
        "F = m * a",
        ["physics"],
    )
    assert note["source"] is None
    assert note["created_at"] and note["updated_at"]


def test_tags_are_trimmed_and_duplicates_dropped(notes_client):
    note = create(notes_client, tags=[" physics ", "exam", "physics", "  "])

    assert note["tags"] == ["physics", "exam"]


@pytest.mark.parametrize(
    "body",
    [
        {"title": "   "},  # a title is required
        {"title": "x" * 201},
        {"title": "ok", "tags": ["t"] * 11},  # at most 10 tags
        {"title": "ok", "tags": ["x" * 31]},  # each tag at most 30 characters
        {"title": "ok", "content": "x" * 50_001},
    ],
)
def test_invalid_notes_are_rejected(notes_client, body):
    response = notes_client.post("/api/notes", json={"content": "", **body})

    assert response.status_code == 422


def test_list_my_notes_most_recently_edited_first(notes_client, db_session):
    older = create(notes_client, title="Older")
    newer = create(notes_client, title="Newer")
    # Explicit times: Windows' clock is too coarse to tell rows made microseconds apart.
    db_session.get(Note, older["id"]).updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.get(Note, newer["id"]).updated_at = datetime(2026, 1, 2, tzinfo=UTC)
    db_session.commit()

    titles = [n["title"] for n in notes_client.get("/api/notes").json()]

    assert titles == ["Newer", "Older"]


def test_edit_a_note(notes_client):
    note = create(notes_client, title="Draft", content="old", tags=["a"])

    response = notes_client.patch(
        f"/api/notes/{note['id']}", json={"content": "F = m * a", "tags": ["physics"]}
    )

    assert response.status_code == 200
    edited = notes_client.get(f"/api/notes/{note['id']}").json()
    assert (edited["title"], edited["content"], edited["tags"]) == (
        "Draft",
        "F = m * a",
        ["physics"],
    )


def test_an_edit_cannot_empty_the_title(notes_client):
    note = create(notes_client)

    assert notes_client.patch(f"/api/notes/{note['id']}", json={"title": " "}).status_code == 422


def test_delete_a_note(notes_client):
    note = create(notes_client)

    assert notes_client.delete(f"/api/notes/{note['id']}").status_code == 204
    assert notes_client.get(f"/api/notes/{note['id']}").status_code == 404


# --- Search ------------------------------------------------------------------------


def search(client, q):
    response = client.get("/api/notes/search", params={"q": q})
    assert response.status_code == 200, response.text
    return sorted(n["title"] for n in response.json())


def test_search_finds_words_in_the_title_content_or_tags_ignoring_case(notes_client):
    create(notes_client, title="Newton's 2nd law", content="F = m * a")
    create(notes_client, title="SQL joins", content="INNER JOIN keeps matching rows")
    create(notes_client, title="Exam plan", content="Revise ch. 3", tags=["physics"])

    assert search(notes_client, "NEWTON") == ["Newton's 2nd law"]  # title, any case
    assert search(notes_client, "matching") == ["SQL joins"]  # content
    assert search(notes_client, "physics") == ["Exam plan"]  # tag
    assert search(notes_client, "nothing like this") == []


def test_percent_and_underscore_are_searched_literally(notes_client):
    create(notes_client, title="Discount", content="20% off")
    create(notes_client, title="Python", content="my_variable")
    create(notes_client, title="Plain", content="no special characters")

    # In SQL LIKE, % means "anything" and _ means "any one character". Unescaped,
    # "%" would match every note and "_" would match any text.
    assert search(notes_client, "%") == ["Discount"]
    assert search(notes_client, "_") == ["Python"]


@pytest.mark.parametrize("q", ["", "   ", "x" * 201])
def test_search_needs_a_sensible_query(notes_client, q):
    assert notes_client.get("/api/notes/search", params={"q": q}).status_code == 422


# --- Saved from a chat answer ------------------------------------------------------


def test_the_chat_reply_gives_the_answer_message_id(notes_client):
    conversation_id = new_conversation(notes_client)

    reply = send(notes_client, "What is Newton's 2nd law?", conversation_id).json()

    messages = notes_client.get(f"/api/conversations/{conversation_id}").json()["messages"]
    assert reply["message_id"] == messages[1]["id"]  # the assistant's answer


def test_save_an_answer_as_a_note_and_see_where_it_came_from(notes_client):
    conversation_id = new_conversation(notes_client)
    reply = send(notes_client, "What is Newton's 2nd law?", conversation_id).json()
    notes_client.patch(f"/api/conversations/{conversation_id}", json={"title": "Physics revision"})

    note = create(
        notes_client,
        title="Newton's 2nd law",
        content=reply["reply"],
        source_message_id=reply["message_id"],
    )

    assert note["content"] == "F = m * a."
    assert note["source"] == {
        "message_id": reply["message_id"],
        "conversation_id": conversation_id,
        "conversation_title": "Physics revision",
    }
    assert search(notes_client, "m * a") == ["Newton's 2nd law"]  # searchable


def test_a_note_cannot_point_to_another_users_message(notes_client, bob, db_session):
    bobs_chat = Conversation(user_id=bob.id)
    bobs_chat.messages.append(Message(position=1, role="assistant", content="Bob's secret"))
    db_session.add(bobs_chat)
    db_session.commit()
    bobs_message_id = bobs_chat.messages[0].id

    response = notes_client.post(
        "/api/notes", json={"title": "x", "content": "", "source_message_id": bobs_message_id}
    )

    assert response.status_code == 404  # same as a message that doesn't exist
    assert db_session.scalars(select(Note)).all() == []


def test_deleting_the_chat_keeps_the_note(notes_client):
    conversation_id = new_conversation(notes_client)
    reply = send(notes_client, "What is Newton's 2nd law?", conversation_id).json()
    note = create(notes_client, content=reply["reply"], source_message_id=reply["message_id"])

    notes_client.delete(f"/api/conversations/{conversation_id}")

    kept = notes_client.get(f"/api/notes/{note['id']}").json()
    assert kept["content"] == "F = m * a."
    assert kept["source"] is None  # the link is gone (ON DELETE SET NULL), the note isn't


# --- Notes belong to one user ------------------------------------------------------


@pytest.mark.parametrize(
    "method, body",
    [("GET", None), ("PATCH", {"title": "mine now"}), ("DELETE", None)],
)
def test_another_users_note_returns_404(notes_client, bob, method, body):
    alices = create(notes_client, title="Alice's note")

    app.dependency_overrides[get_current_user_id] = lambda: bob.id
    response = notes_client.request(method, f"/api/notes/{alices['id']}", json=body)

    assert response.status_code == 404
    assert notes_client.get("/api/notes").json() == []
    assert search(notes_client, "Alice") == []


# --- N+1: listing notes with their source chat ------------------------------------


def make_saved_notes(db_session, user_id: str, count: int) -> None:
    for n in range(count):
        chat = Conversation(user_id=user_id, title=f"Chat {n}")
        message = Message(position=1, role="assistant", content=f"answer {n}")
        chat.messages.append(message)
        db_session.add_all(
            [chat, Note(user_id=user_id, title=f"Note {n}", content="", source_message=message)]
        )
    db_session.commit()
    db_session.expunge_all()  # start from the database, like a new request


@pytest.mark.parametrize("count", [1, 10])
def test_listing_notes_with_their_source_chat_is_three_queries_however_many(db_session, count):
    user = User(email="n1@example.com")
    db_session.add(user)
    db_session.commit()
    make_saved_notes(db_session, user.id, count)
    statements: list[str] = []
    event.listen(
        db_session.get_bind(), "before_cursor_execute", lambda *args: statements.append(args[2])
    )

    notes = repo.list_notes(db_session, user.id)
    titles = [n.source_message.conversation.title for n in notes]  # touch every source

    assert len(titles) == count
    assert len(statements) == 3  # notes, then their messages, then those messages' chats
