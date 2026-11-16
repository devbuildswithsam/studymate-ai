"""Two-user isolation: user B can never see or change user A's data. SMA-34 (guide 7.1a).

The app runs single-user (AUTH_MODE=local), but every query is already scoped by user_id.
These tests prove it with two real users. B always gets 404, exactly like an id that
doesn't exist: a 403 would tell B that A's item exists.

KEEP THIS FILE GROWING: every route with an id in its path must have a case in
ISOLATION_CASES. test_every_route_with_an_id_is_covered fails when a new one is missing
(tasks and documents in later stages).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.deps import get_current_user
from app.main import app
from app.models import Conversation, LLMCall, Message, Note, User
from app.services.llm.fake import FakeProvider
from tests.test_conversations_api import use_fakes

UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def two_users(db_session) -> tuple[User, User]:
    alice = User(email="alice@example.com", name="Alice")
    bob = User(email="bob@example.com", name="Bob")
    db_session.add_all([alice, bob])
    db_session.commit()
    return alice, bob


@pytest.fixture
def api(client, two_users):
    """The test client, a fake AI, and as(user) to choose who is making the requests."""
    use_fakes({"main": FakeProvider(replies=["F = m * a."]), "backup": FakeProvider()})

    def act_as(user: User) -> TestClient:
        # The one place identity comes from: replacing it here is how a test "logs in".
        app.dependency_overrides[get_current_user] = lambda: user
        return client

    return act_as


@pytest.fixture
def alices_data(api, two_users) -> dict[str, str]:
    """Alice's chat (with a title and messages) and a note saved from its answer."""
    alice, _ = two_users
    client = api(alice)
    conversation_id = client.post("/api/conversations", json={}).json()["id"]
    reply = client.post(
        f"/api/conversations/{conversation_id}/messages", json={"message": "Newton's 2nd law?"}
    ).json()
    client.patch(f"/api/conversations/{conversation_id}", json={"title": "Alice's physics"})
    note_id = client.post(
        "/api/notes",
        json={
            "title": "Alice's note",
            "content": "F = m * a",
            "source_message_id": reply["message_id"],
        },
    ).json()["id"]
    return {"conversation": conversation_id, "message": reply["message_id"], "note": note_id}


def fingerprint(db_session) -> dict:
    """Alice's rows as they are in the database, to prove B's requests changed nothing."""
    db_session.expire_all()
    return {
        "conversations": db_session.execute(
            select(Conversation.id, Conversation.title, Conversation.model)
        ).all(),
        "messages": db_session.scalar(select(func.count()).select_from(Message)),
        "notes": db_session.execute(select(Note.id, Note.title, Note.content, Note.tags)).all(),
        "llm_calls": db_session.scalar(select(func.count()).select_from(LLMCall)),
    }


# --- Every route with an id: B gets 404 and nothing changes -----------------------

# (method, path with {placeholders}, JSON body). The placeholders are filled with Alice's ids.
ISOLATION_CASES = [
    ("GET", "/api/conversations/{conversation_id}", None),
    ("PATCH", "/api/conversations/{conversation_id}", {"title": "Bob was here"}),
    ("DELETE", "/api/conversations/{conversation_id}", None),
    ("POST", "/api/conversations/{conversation_id}/messages", {"message": "hi"}),
    ("POST", "/api/conversations/{conversation_id}/title", None),
    ("GET", "/api/notes/{note_id}", None),
    ("PATCH", "/api/notes/{note_id}", {"title": "Bob was here", "content": "x"}),
    ("DELETE", "/api/notes/{note_id}", None),
]


def fill(path: str, ids: dict[str, str]) -> str:
    return path.format(conversation_id=ids["conversation"], note_id=ids["note"])


@pytest.mark.parametrize(
    "method, path, body", ISOLATION_CASES, ids=[f"{m} {p}" for m, p, _ in ISOLATION_CASES]
)
def test_b_gets_404_on_a_s_items_and_nothing_changes(
    api, two_users, alices_data, db_session, method, path, body
):
    _, bob = two_users
    before = fingerprint(db_session)

    response = api(bob).request(method, fill(path, alices_data), json=body)

    assert response.status_code == 404  # not 403: that would confirm A's item exists
    assert response.json()["error"]["code"] == "not_found"
    assert fingerprint(db_session) == before


@pytest.mark.parametrize(
    "method, path, body", ISOLATION_CASES, ids=[f"{m} {p}" for m, p, _ in ISOLATION_CASES]
)
def test_a_s_item_looks_exactly_like_one_that_never_existed(
    api, two_users, alices_data, method, path, body
):
    _, bob = two_users
    client = api(bob)
    unknown = {"conversation": UNKNOWN_ID, "note": UNKNOWN_ID}

    alices = client.request(method, fill(path, alices_data), json=body)
    missing = client.request(method, fill(path, unknown), json=body)

    assert (alices.status_code, alices.json()) == (missing.status_code, missing.json())


def test_every_route_with_an_id_is_covered():
    """New routes with an {id} must be added to ISOLATION_CASES (tasks, documents...)."""
    # The OpenAPI schema (what /docs shows) lists every endpoint. app.routes doesn't: in
    # this FastAPI version it holds wrappers for the included routers, without paths.
    routes_with_an_id = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if "{" in path
        for method in operations
    }
    covered = {(method, path) for method, path, _ in ISOLATION_CASES}

    assert len(routes_with_an_id) >= len(ISOLATION_CASES)  # the scan really sees routes
    assert routes_with_an_id - covered == set(), "add these routes to ISOLATION_CASES"


# --- Lists, search and links ------------------------------------------------------


def test_b_s_lists_and_search_do_not_show_a_s_items(api, two_users, alices_data):
    _, bob = two_users
    client = api(bob)

    assert client.get("/api/conversations").json() == []
    assert client.get("/api/notes").json() == []
    assert client.get("/api/notes/search", params={"q": "Alice"}).json() == []
    assert client.get("/api/notes/search", params={"q": "m * a"}).json() == []


def test_b_cannot_save_a_note_from_a_s_message(api, two_users, alices_data, db_session):
    _, bob = two_users
    before = fingerprint(db_session)

    response = api(bob).post(
        "/api/notes",
        json={"title": "stolen", "content": "", "source_message_id": alices_data["message"]},
    )

    assert response.status_code == 404
    assert fingerprint(db_session) == before


def test_b_s_own_items_are_separate_from_a_s(api, two_users, alices_data):
    alice, bob = two_users
    bobs_note = api(bob).post("/api/notes", json={"title": "Bob's note", "content": ""}).json()

    assert [n["title"] for n in api(bob).get("/api/notes").json()] == ["Bob's note"]
    assert [n["title"] for n in api(alice).get("/api/notes").json()] == ["Alice's note"]
    assert api(alice).get(f"/api/notes/{bobs_note['id']}").status_code == 404  # both ways


def test_a_still_sees_everything_after_b_tried(api, two_users, alices_data):
    alice, bob = two_users
    for method, path, body in ISOLATION_CASES:
        api(bob).request(method, fill(path, alices_data), json=body)

    client = api(alice)
    chat = client.get(f"/api/conversations/{alices_data['conversation']}").json()
    note = client.get(f"/api/notes/{alices_data['note']}").json()

    assert chat["title"] == "Alice's physics"
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    assert (note["title"], note["content"]) == ("Alice's note", "F = m * a")
    assert note["source"]["message_id"] == alices_data["message"]
