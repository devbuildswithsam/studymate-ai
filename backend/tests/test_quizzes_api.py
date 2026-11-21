"""The quizzes API: make a quiz from a document, take it, get the score. SMA-63, test-first.

The right answers stay on the server: the quiz sent to the browser has the questions and
options only; an attempt is scored here and only then returns answers and explanations.
"""

import json

import pytest
from sqlalchemy import func, select

from app.main import app
from app.models import LLMCall, Quiz, QuizAttempt
from app.services.llm.fake import FakeProvider
from app.services.llm.fallback import FallbackManager, get_fallback_manager
from app.services.llm.registry import get_registry
from tests.pdf_maker import make_pdf
from tests.test_quiz import REGISTRY, quiz_json

PAGES = [
    "Heat flows from a hot object to a cold one until both reach the same temperature.",
    "Entropy always increases in an isolated system; it measures disorder.",
]


@pytest.fixture
def ai(client, physics) -> FakeProvider:
    """The quiz AI: a fake JSON-capable model (set .replies in a test). Set up AFTER the
    upload, whose summary step (SMA-50) uses the default fake AI."""
    fake = FakeProvider(
        replies=[quiz_json(5, page=1)], model_config={"id": "json-model", "supports_json": True}
    )
    manager = FallbackManager(REGISTRY, lambda model: fake)
    app.dependency_overrides[get_registry] = lambda: REGISTRY
    app.dependency_overrides[get_fallback_manager] = lambda: manager
    return fake


@pytest.fixture
def physics(client) -> dict:
    response = client.post(
        "/api/documents", files={"file": ("Physics.pdf", make_pdf(PAGES), "application/pdf")}
    )
    document = json.loads(response.text.splitlines()[-1])["document"]
    assert document["status"] == "ready"
    return document


def make_quiz(client, document_id: str, questions: int = 5):
    return client.post("/api/quizzes", json={"document_id": document_id, "questions": questions})


def count(db_session, model) -> int:
    db_session.expire_all()
    return db_session.scalar(select(func.count()).select_from(model))


# --- Making a quiz --------------------------------------------------------------------------


def test_a_quiz_is_made_from_the_document_without_showing_the_answers(
    client, ai, physics, db_session
):
    response = make_quiz(client, physics["id"])

    assert response.status_code == 201
    quiz = response.json()
    assert quiz["title"] == "Photosynthesis" and quiz["document_name"] == "Physics.pdf"
    assert len(quiz["questions"]) == 5
    first = quiz["questions"][0]
    assert set(first) == {"question", "options", "page"}  # no answer, no explanation
    assert first["page"] == 1  # both short pages fit in one chunk, which starts on page 1
    # The model saw the document's own text, labelled with its pages.
    assert "[page 1]" in ai.calls[0][-1]["content"]
    assert "Entropy always increases" in ai.calls[0][-1]["content"]
    # Stored with the answers, and the AI call is logged.
    stored = db_session.get(Quiz, quiz["id"])
    assert stored.questions[0]["answer"] == 0
    calls = db_session.scalars(select(LLMCall).where(LLMCall.mode == "quiz")).all()
    assert [c.status for c in calls] == ["ok"]


def test_ten_questions_can_be_asked_for_but_not_seven(client, ai, physics):
    ai.replies = [quiz_json(10, page=1)]

    assert len(make_quiz(client, physics["id"], 10).json()["questions"]) == 10
    assert make_quiz(client, physics["id"], 7).status_code == 422


def test_a_bad_answer_is_repaired_once(client, ai, physics):
    ai.replies = ["Here's a quiz: what is entropy?", quiz_json(5)]

    assert make_quiz(client, physics["id"]).status_code == 201
    assert len(ai.calls) == 2


def test_two_bad_answers_are_a_clear_error_and_save_nothing(client, ai, physics, db_session):
    ai.replies = ["no", "still no"]

    response = make_quiz(client, physics["id"])

    assert response.status_code == 503
    assert "couldn't write a valid quiz" in response.json()["error"]["message"]
    assert count(db_session, Quiz) == 0
    db_session.expire_all()
    quiz_calls = db_session.scalars(select(LLMCall).where(LLMCall.mode == "quiz")).all()
    assert len(quiz_calls) == 2  # both calls logged


def test_an_unknown_document_is_404(client, ai):
    assert make_quiz(client, "00000000-0000-0000-0000-000000000000").status_code == 404


def test_a_document_that_is_not_ready_is_refused(client, ai, physics, db_session):
    from app.models import Document

    document = db_session.get(Document, physics["id"])
    document.status = "processing"
    db_session.commit()

    response = make_quiz(client, physics["id"])

    assert response.status_code == 409
    assert ai.calls == []  # no AI call for nothing


# --- Taking it ------------------------------------------------------------------------------


@pytest.fixture
def quiz(client, ai, physics) -> dict:
    return make_quiz(client, physics["id"]).json()  # every right answer is option 0


def test_an_attempt_is_scored_on_the_server_with_explanations(client, quiz, db_session):
    response = client.post(
        f"/api/quizzes/{quiz['id']}/attempts", json={"answers": [0, 1, 0, None, 0]}
    )

    assert response.status_code == 201
    result = response.json()
    assert (result["score"], result["total"]) == (3, 5)
    second = result["results"][1]
    assert second == {
        "chosen": 1,
        "correct_answer": 0,
        "is_correct": False,
        "explanation": "Chlorophyll reflects green light (page 2).",
        "page": 1,
    }
    assert result["results"][3]["is_correct"] is False  # unanswered counts as wrong
    assert count(db_session, QuizAttempt) == 1  # saved for Progress


@pytest.mark.parametrize("answers", [[0, 0], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 4]])
def test_an_attempt_needs_one_valid_answer_per_question(client, quiz, answers):
    response = client.post(f"/api/quizzes/{quiz['id']}/attempts", json={"answers": answers})

    assert response.status_code == 422


def test_the_list_shows_attempts_and_the_best_score(client, quiz):
    client.post(f"/api/quizzes/{quiz['id']}/attempts", json={"answers": [0, 0, 0, 0, 0]})
    client.post(f"/api/quizzes/{quiz['id']}/attempts", json={"answers": [1, 1, 0, 0, 0]})

    [listed] = client.get("/api/quizzes").json()

    assert listed["id"] == quiz["id"]
    assert (listed["question_count"], listed["attempts"]) == (5, 2)
    assert (listed["best_score"], listed["last_score"]) == (5, 3)


def test_a_quiz_can_be_opened_again_without_its_answers(client, quiz):
    opened = client.get(f"/api/quizzes/{quiz['id']}").json()

    assert opened["questions"] == quiz["questions"]


def test_deleting_a_quiz_deletes_its_attempts(client, quiz, db_session):
    client.post(f"/api/quizzes/{quiz['id']}/attempts", json={"answers": [0, 0, 0, 0, 0]})

    assert client.delete(f"/api/quizzes/{quiz['id']}").status_code == 204

    assert count(db_session, Quiz) == count(db_session, QuizAttempt) == 0
    assert client.get(f"/api/quizzes/{quiz['id']}").status_code == 404


def test_deleting_the_document_keeps_the_quiz(client, quiz, physics):
    client.delete(f"/api/documents/{physics['id']}")

    kept = client.get(f"/api/quizzes/{quiz['id']}").json()

    assert kept["document_id"] is None and kept["document_name"] == "Physics.pdf"
