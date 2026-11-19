"""The study chat through the API (guide 6.2, 7.3, 7.5). SMA-49, test-first.

Done when: answers cite the right pages, and unanswerable questions show the not-found
notice instead of a guess. The AI is a FakeProvider; uploads use conftest's fake embedder.
"""

import json

import pytest
from sqlalchemy import select

from app.models import Document, LLMCall, User
from app.services.llm.fake import FakeProvider
from app.services.study import NOT_FOUND_TEXT
from tests.pdf_maker import make_pdf
from tests.test_conversations_api import use_fakes

PAGES = [
    "Heat flows from a hot object to a cold one until both reach the same temperature.",
    "Entropy always increases in an isolated system; it measures disorder.",
]


@pytest.fixture
def ai(client) -> FakeProvider:
    fake = FakeProvider(replies=["Entropy always increases [1]."])
    use_fakes({"main": fake, "backup": FakeProvider()})
    return fake


@pytest.fixture
def physics(client) -> dict:
    response = client.post(
        "/api/documents", files={"file": ("Physics.pdf", make_pdf(PAGES), "application/pdf")}
    )
    document = json.loads(response.text.splitlines()[-1])["document"]
    assert document["status"] == "ready"
    return document


def study_chat(client, *document_ids) -> dict:
    response = client.post(
        "/api/conversations", json={"mode": "study", "document_ids": list(document_ids)}
    )
    assert response.status_code == 201, response.text
    return response.json()


def ask(client, conversation_id, message="What is entropy?", **extra):
    return client.post(
        f"/api/conversations/{conversation_id}/messages", json={"message": message, **extra}
    )


# --- Study chats and their documents --------------------------------------------------------------


def test_a_study_chat_is_created_with_its_documents(client, physics):
    chat = study_chat(client, physics["id"])

    assert chat["mode"] == "study"
    assert chat["documents"] == [{"id": physics["id"], "filename": "Physics.pdf"}]
    listed = client.get("/api/conversations").json()
    assert [c["mode"] for c in listed] == ["study"]  # the sidebar knows where to open it


def test_the_documents_of_a_study_chat_can_be_changed(client, physics):
    chat = study_chat(client, physics["id"])

    response = client.put(f"/api/conversations/{chat['id']}/documents", json={"document_ids": []})

    assert response.json()["documents"] == []
    assert client.get(f"/api/conversations/{chat['id']}").json()["documents"] == []


def test_another_users_document_cannot_be_added(client, db_session):
    bob = User(email="bob@example.com")
    db_session.add(bob)
    db_session.flush()
    bobs = Document(user_id=bob.id, filename="Bob.pdf", mime_type="application/pdf", size_bytes=1)
    db_session.add(bobs)
    db_session.commit()

    response = client.post("/api/conversations", json={"mode": "study", "document_ids": [bobs.id]})

    assert response.status_code == 404  # same answer as a document that doesn't exist


def test_a_general_chat_has_no_documents_to_change(client, physics):
    chat_id = client.post("/api/conversations", json={}).json()["id"]

    response = client.put(
        f"/api/conversations/{chat_id}/documents", json={"document_ids": [physics["id"]]}
    )

    assert response.status_code == 400


# --- Done when: answers cite the right pages ------------------------------------------------------


def test_a_study_answer_is_grounded_with_citations_to_pages(client, ai, physics):
    chat = study_chat(client, physics["id"])

    reply = ask(client, chat["id"]).json()

    assert reply["mode"] == "grounded"
    assert reply["reply"] == "Entropy always increases [1]."
    [citation] = reply["citations"]
    assert (citation["n"], citation["filename"]) == (1, "Physics.pdf")
    assert citation["page"] == 1  # both short pages fit in one chunk, which starts on page 1
    assert "Entropy always increases" in citation["text"]  # the chunk the answer came from
    prompt = ai.calls[0][-1]["content"]
    assert '<source n="1" document="Physics.pdf"' in prompt


def test_citations_are_saved_with_the_answer(client, ai, physics):
    chat = study_chat(client, physics["id"])
    ask(client, chat["id"])

    saved = client.get(f"/api/conversations/{chat['id']}").json()["messages"][-1]

    assert saved["mode"] == "grounded"
    assert [c["filename"] for c in saved["citations"]] == ["Physics.pdf"]


def test_every_model_call_is_logged_as_grounded(client, ai, physics, db_session):
    chat = study_chat(client, physics["id"])
    ask(client, chat["id"])

    assert [c.mode for c in db_session.scalars(select(LLMCall))] == ["grounded"]


# --- Done when: unanswerable questions show the not-found notice ------------------------------------


def test_an_unanswerable_question_gets_the_not_found_notice(client, ai, physics):
    ai.replies = ["NOT_FOUND"]
    chat = study_chat(client, physics["id"])

    reply = ask(client, chat["id"], "Who won the 1998 World Cup?").json()

    assert (reply["mode"], reply["reply"], reply["citations"]) == ("grounded", NOT_FOUND_TEXT, [])


def test_answer_from_general_knowledge_skips_the_documents(client, ai, physics):
    ai.replies = ["France won the 1998 World Cup."]
    chat = study_chat(client, physics["id"])

    reply = ask(client, chat["id"], "Who won the 1998 World Cup?", general=True).json()

    assert (reply["mode"], reply["citations"]) == ("general", [])
    assert "<source" not in ai.calls[0][-1]["content"]  # no documents were sent


# --- When a study answer isn't possible -------------------------------------------------------------


def test_a_study_chat_without_documents_says_so(client, ai, physics):
    chat = study_chat(client)

    response = ask(client, chat["id"])

    assert response.status_code == 400
    assert "Add at least one document" in response.json()["error"]["message"]


def test_a_general_chat_is_unchanged(client, ai):
    ai.replies = ["Water moves through a membrane."]
    chat_id = client.post("/api/conversations", json={}).json()["id"]

    reply = ask(client, chat_id, "What is osmosis?").json()

    assert (reply["mode"], reply["citations"]) == ("general", [])
