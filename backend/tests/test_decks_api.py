"""The flashcards API: decks from a document or an AI answer, and reviewing them. SMA-64.

Written test-first. A card counts as known when its LATEST review says "knew it".
"""

import json

import pytest
from sqlalchemy import func, select

from app.db.seed import find_local_user
from app.main import app
from app.models import CardReview, Conversation, Deck, LLMCall, Message, User
from app.services.llm.fake import FakeProvider
from app.services.llm.fallback import FallbackManager, get_fallback_manager
from app.services.llm.registry import get_registry
from tests.pdf_maker import make_pdf
from tests.test_flashcards import deck_json
from tests.test_quiz import REGISTRY

PAGES = [
    "Heat flows from a hot object to a cold one until both reach the same temperature.",
    "Entropy always increases in an isolated system; it measures disorder.",
]
ANSWER = "Entropy measures disorder. In an isolated system it always increases."


@pytest.fixture
def physics(client) -> dict:
    response = client.post(
        "/api/documents", files={"file": ("Physics.pdf", make_pdf(PAGES), "application/pdf")}
    )
    document = json.loads(response.text.splitlines()[-1])["document"]
    assert document["status"] == "ready"
    return document


@pytest.fixture
def ai(client, physics) -> FakeProvider:
    """The flashcards AI (set up AFTER the upload, whose summary step uses the default AI)."""
    fake = FakeProvider(
        replies=[deck_json(10, page=1)], model_config={"id": "json-model", "supports_json": True}
    )
    manager = FallbackManager(REGISTRY, lambda model: fake)
    app.dependency_overrides[get_registry] = lambda: REGISTRY
    app.dependency_overrides[get_fallback_manager] = lambda: manager
    return fake


def a_chat(
    db_session, user: User, title: str | None = "Thermodynamics revision"
) -> tuple[str, str]:
    """One saved chat with a question and an AI answer. Returns (question id, answer id)."""
    chat = Conversation(user_id=user.id, title=title)
    db_session.add(chat)
    db_session.flush()
    question = Message(conversation_id=chat.id, position=1, role="user", content="What is entropy?")
    answer = Message(conversation_id=chat.id, position=2, role="assistant", content=ANSWER)
    db_session.add_all([question, answer])
    db_session.commit()
    return question.id, answer.id


@pytest.fixture
def my_answer(db_session, client) -> str:
    return a_chat(db_session, find_local_user(db_session))[1]


def make_deck(client, **source):
    return client.post("/api/decks", json=source)


def count(db_session, model) -> int:
    db_session.expire_all()
    return db_session.scalar(select(func.count()).select_from(model))


# --- Making a deck ---------------------------------------------------------------------------


def test_a_deck_from_a_document(client, ai, physics, db_session):
    response = make_deck(client, document_id=physics["id"])

    assert response.status_code == 201
    deck = response.json()
    assert (deck["source_type"], deck["source_name"]) == ("document", "Physics.pdf")
    assert len(deck["cards"]) == 10
    assert deck["cards"][0] == {
        "front": "Card 0: what does chlorophyll reflect?",
        "back": "Green light.",
        "page": 1,
        "last": None,
    }
    assert "Entropy always increases" in ai.calls[0][-1]["content"]
    calls = db_session.scalars(select(LLMCall).where(LLMCall.mode == "flashcards")).all()
    assert [c.status for c in calls] == ["ok"]


def test_a_deck_from_one_of_my_answers(client, ai, my_answer):
    ai.replies = [deck_json(5, page=None)]

    response = make_deck(client, message_id=my_answer)

    assert response.status_code == 201
    deck = response.json()
    assert (deck["source_type"], deck["source_name"]) == ("answer", "Thermodynamics revision")
    assert len(deck["cards"]) == 5
    assert ANSWER in ai.calls[0][-1]["content"]  # made from the answer's own text
    assert "an answer the AI gave" in ai.calls[0][0]["content"]


def test_a_question_i_typed_is_not_an_answer(client, ai, db_session):
    question, _ = a_chat(db_session, find_local_user(db_session))

    response = make_deck(client, message_id=question)

    assert response.status_code == 400
    assert ai.calls == []


def test_someone_elses_answer_is_404(client, ai, db_session):
    bob = User(email="bob@example.com")
    db_session.add(bob)
    db_session.commit()
    _, bobs_answer = a_chat(db_session, bob)

    assert make_deck(client, message_id=bobs_answer).status_code == 404
    assert ai.calls == []


@pytest.mark.parametrize(
    "source", [{}, {"document_id": "d", "message_id": "m"}], ids=["neither", "both"]
)
def test_exactly_one_source(client, ai, source):
    assert make_deck(client, **source).status_code == 422


def test_a_document_that_is_not_ready_is_refused(client, ai, physics, db_session):
    from app.models import Document

    db_session.get(Document, physics["id"]).status = "processing"
    db_session.commit()

    assert make_deck(client, document_id=physics["id"]).status_code == 409


def test_two_bad_answers_save_nothing(client, ai, physics, db_session):
    ai.replies = ["no", "still no"]

    response = make_deck(client, document_id=physics["id"])

    assert response.status_code == 503
    assert "broke the rules twice" in response.json()["error"]["message"]
    assert count(db_session, Deck) == 0
    calls = db_session.scalars(select(LLMCall).where(LLMCall.mode == "flashcards")).all()
    assert len(calls) == 2  # both failed calls are logged


# --- Reviewing ------------------------------------------------------------------------------


@pytest.fixture
def deck(client, ai, physics) -> dict:
    return make_deck(client, document_id=physics["id"]).json()


def review(client, deck_id: str, card: int, knew: bool):
    return client.post(f"/api/decks/{deck_id}/reviews", json={"card": card, "knew": knew})


def test_a_review_is_saved_and_the_latest_mark_counts(client, deck, db_session):
    first = review(client, deck["id"], 0, True)
    assert first.status_code == 201
    assert first.json() == {"card_count": 10, "reviewed": 1, "known": 1}

    again = review(client, deck["id"], 0, False).json()  # forgot it after all

    assert (again["reviewed"], again["known"]) == (1, 0)
    assert count(db_session, CardReview) == 2  # both kept, for Progress


@pytest.mark.parametrize("card", [-1, 10])
def test_a_card_that_does_not_exist_is_refused(client, deck, card):
    assert review(client, deck["id"], card, True).status_code == 422


def test_the_list_and_the_deck_show_how_reviewing_went(client, deck):
    review(client, deck["id"], 0, True)
    review(client, deck["id"], 1, False)

    [listed] = client.get("/api/decks").json()
    opened = client.get(f"/api/decks/{deck['id']}").json()

    assert (listed["card_count"], listed["reviewed"], listed["known"]) == (10, 2, 1)
    assert [c["last"] for c in opened["cards"][:3]] == ["knew", "didnt", None]


def test_deleting_a_deck_deletes_its_reviews(client, deck, db_session):
    review(client, deck["id"], 0, True)

    assert client.delete(f"/api/decks/{deck['id']}").status_code == 204

    assert count(db_session, Deck) == count(db_session, CardReview) == 0


def test_deleting_the_chat_keeps_a_deck_made_from_its_answer(client, ai, my_answer, db_session):
    ai.replies = [deck_json(5, page=None)]
    deck = make_deck(client, message_id=my_answer).json()
    chat_id = db_session.get(Message, my_answer).conversation_id

    client.delete(f"/api/conversations/{chat_id}")

    kept = client.get(f"/api/decks/{deck['id']}").json()
    assert kept["source_name"] == "Thermodynamics revision" and len(kept["cards"]) == 5
