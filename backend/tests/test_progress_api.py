"""The Progress dashboard's numbers: GET /api/progress. SMA-65, test-first.

Every number is checked on data set up here by hand, next to another user's data that
must never count.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.db.seed import find_local_user
from app.models import (
    CardReview,
    Conversation,
    Deck,
    Document,
    Quiz,
    QuizAttempt,
    Task,
    User,
)
from app.models.document import conversation_documents

TODAY = date(2026, 11, 21)
NOW = datetime.now(UTC)


def quiz_with_attempts(db, user, title: str, scores: list[tuple[int, int]], document=None):
    quiz = Quiz(
        user_id=user.id,
        document_id=document.id if document else None,
        document_name="Doc.pdf",
        title=title,
        questions=[
            {
                "question": "q",
                "options": ["a", "b", "c", "d"],
                "answer": 0,
                "explanation": "e",
                "page": None,
            }
        ],
    )
    db.add(quiz)
    db.flush()
    for n, (score, total) in enumerate(scores):
        db.add(
            QuizAttempt(
                quiz_id=quiz.id,
                user_id=user.id,
                answers=[0],
                score=score,
                total=total,
                created_at=NOW - timedelta(hours=10 - n),  # oldest first
            )
        )
    return quiz


def deck_with_reviews(db, user, marks: list[tuple[int, bool]], document=None):
    deck = Deck(
        user_id=user.id,
        title="Cards",
        source_type="document",
        source_name="Doc.pdf",
        document_id=document.id if document else None,
        cards=[{"front": f"f{i}", "back": "b", "page": None} for i in range(4)],
    )
    db.add(deck)
    db.flush()
    for n, (card, knew) in enumerate(marks):
        db.add(
            CardReview(
                deck_id=deck.id,
                user_id=user.id,
                card_index=card,
                knew=knew,
                created_at=NOW - timedelta(minutes=60 - n),
            )
        )
    return deck


def document(db, user, name: str, status: str = "ready") -> Document:
    doc = Document(
        user_id=user.id, filename=name, mime_type="application/pdf", size_bytes=1, status=status
    )
    db.add(doc)
    db.flush()
    return doc


@pytest.fixture
def me(client, db_session) -> User:
    return find_local_user(db_session)


@pytest.fixture
def someone_else(db_session) -> User:
    """Another user with lots of activity: none of it may ever show up in my numbers."""
    bob = User(email="bob@example.com")
    db_session.add(bob)
    db_session.flush()
    doc = document(db_session, bob, "Bobs.pdf")
    quiz_with_attempts(db_session, bob, "Bob's quiz", [(5, 5)] * 4, doc)
    deck_with_reviews(db_session, bob, [(0, True), (1, True), (2, True)], doc)
    db_session.add_all(
        [Task(user_id=bob.id, title="Bob's", status="done", completed_at=NOW) for _ in range(3)]
    )
    db_session.commit()
    return bob


def progress(client):
    response = client.get("/api/progress", params={"today": TODAY.isoformat()})
    assert response.status_code == 200
    return response.json()


def test_a_new_user_sees_zeros(client, someone_else):
    data = progress(client)

    assert data["quizzes"] == {"attempts": 0, "average_percent": None, "history": []}
    assert data["flashcards"] == {"decks": 0, "cards_reviewed": 0, "cards_known": 0, "reviews": 0}
    assert data["tasks"] == {"done_last_7_days": 0, "open": 0, "overdue": 0}
    assert data["documents"] == {"ready": 0, "studied": 0}


def test_quiz_attempts_average_and_history(client, me, someone_else, db_session):
    quiz_with_attempts(db_session, me, "Entropy", [(2, 5), (4, 5)])
    quiz_with_attempts(db_session, me, "Cells", [(9, 10)])
    db_session.commit()

    quizzes = progress(client)["quizzes"]

    assert quizzes["attempts"] == 3
    assert quizzes["average_percent"] == 70  # each attempt counts equally: (40 + 80 + 90) / 3
    titles = [h["quiz_title"] for h in quizzes["history"]]
    assert sorted(titles) == ["Cells", "Entropy", "Entropy"]
    assert {(h["score"], h["total"]) for h in quizzes["history"]} == {(2, 5), (4, 5), (9, 10)}


def test_flashcards_count_the_latest_mark_per_card(client, me, someone_else, db_session):
    # card 0: didn't, then knew -> known. card 1: knew, then didn't -> not known.
    # card 2: didn't, then knew -> known. (Reading the marks backwards would give 1, not 2.)
    marks = [(0, False), (0, True), (1, True), (1, False), (2, False), (2, True)]
    deck_with_reviews(db_session, me, marks)
    db_session.commit()

    cards = progress(client)["flashcards"]

    assert cards == {"decks": 1, "cards_reviewed": 3, "cards_known": 2, "reviews": 6}


def test_tasks_done_lately_open_and_overdue(client, me, someone_else, db_session):
    db_session.add_all(
        [
            Task(user_id=me.id, title="done today", status="done", completed_at=NOW),
            Task(
                user_id=me.id,
                title="done 6 days ago",
                status="done",
                completed_at=NOW - timedelta(days=6),
            ),
            Task(
                user_id=me.id,
                title="done 9 days ago",
                status="done",
                completed_at=NOW - timedelta(days=9),
            ),
            Task(user_id=me.id, title="late", status="todo", due_date=TODAY - timedelta(days=1)),
            Task(user_id=me.id, title="due today", status="doing", due_date=TODAY),  # not late yet
            Task(user_id=me.id, title="no date", status="todo"),
        ]
    )
    db_session.commit()

    assert progress(client)["tasks"] == {"done_last_7_days": 2, "open": 3, "overdue": 1}


def test_documents_studied_means_used_in_a_study_chat_quiz_or_deck(
    client, me, someone_else, db_session
):
    in_chat = document(db_session, me, "Chat.pdf")
    in_quiz = document(db_session, me, "Quiz.pdf")
    in_deck = document(db_session, me, "Deck.pdf")
    document(db_session, me, "Unread.pdf")
    document(db_session, me, "Broken.pdf", status="failed")  # not ready: not counted
    chat = Conversation(user_id=me.id, mode="study")
    db_session.add(chat)
    db_session.flush()
    db_session.execute(
        conversation_documents.insert().values(conversation_id=chat.id, document_id=in_chat.id)
    )
    quiz_with_attempts(db_session, me, "Q", [], in_quiz)
    deck_with_reviews(db_session, me, [], in_deck)
    db_session.commit()

    assert progress(client)["documents"] == {"ready": 4, "studied": 3}


def test_today_is_required_and_must_be_a_date(client):
    assert client.get("/api/progress").status_code == 422
    assert client.get("/api/progress", params={"today": "tomorrow"}).status_code == 422
