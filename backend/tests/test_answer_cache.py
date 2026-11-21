"""A cache for identical study questions (SMA-67), test-first.

Students often ask the same first question again ("What is entropy?") in a new study chat
on the same notes. The answer is then reused instead of paying for a second AI call.
Identical means: the same user, the same documents, the same question (ignoring case and
spaces), the same earlier messages, and the same model choice. Kept for an hour.
"""

import json

import pytest

from app.main import app
from app.services.answer_cache import AnswerCache, cache_key, get_answer_cache
from app.services.llm.exceptions import ProviderUnavailableError
from app.services.llm.fake import FakeProvider
from tests.pdf_maker import make_pdf
from tests.test_chat_stream import events
from tests.test_conversations_api import use_fakes
from tests.test_study_chat import PAGES, ask, study_chat

# --- The key and the cache on their own --------------------------------------------------------


def key(**changes) -> str:
    parts = {
        "user_id": "alice",
        "document_ids": ["d1", "d2"],
        "question": "What is entropy?",
        "history": [],
        "model_id": "main",
        "allow_fallback": True,
        **changes,
    }
    return cache_key(**parts)


def test_the_same_question_in_other_words_case_or_spacing_is_the_same_key():
    assert key(question="  what is   ENTROPY? ") == key()
    assert key(document_ids=["d2", "d1"]) == key()  # the order of the documents doesn't matter


@pytest.mark.parametrize(
    "change",
    [
        {"user_id": "bob"},  # never share answers between users
        {"document_ids": ["d1"]},
        {"question": "What is enthalpy?"},
        {"history": [{"role": "user", "content": "Hi"}]},  # a follow-up means something else
        {"model_id": "backup"},
        {"allow_fallback": False},
    ],
    ids=["user", "documents", "question", "history", "model", "fallback"],
)
def test_anything_else_that_differs_is_another_key(change):
    assert key(**change) != key()


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_an_entry_expires_after_its_time():
    clock = FakeClock()
    cache = AnswerCache(ttl_seconds=3600, clock=clock)
    cache.put("k", {"reply": "Entropy rises."})

    clock.now += 3599
    assert cache.get("k") == {"reply": "Entropy rises."}
    clock.now += 2
    assert cache.get("k") is None


def test_the_oldest_entry_goes_when_the_cache_is_full():
    cache = AnswerCache(max_entries=2)
    cache.put("a", {"n": 1})
    cache.put("b", {"n": 2})
    cache.put("c", {"n": 3})

    assert cache.get("a") is None
    assert cache.get("b") == {"n": 2} and cache.get("c") == {"n": 3}


# --- Through the study chat ------------------------------------------------------------------------


@pytest.fixture
def ai(client) -> FakeProvider:
    fake = FakeProvider(replies=["Entropy always increases [1]."])
    use_fakes({"main": fake, "backup": FakeProvider()})
    return fake


def upload(client, name: str) -> dict:
    response = client.post(
        "/api/documents", files={"file": (name, make_pdf(PAGES), "application/pdf")}
    )
    return json.loads(response.text.splitlines()[-1])["document"]


@pytest.fixture
def physics(client) -> dict:
    return upload(client, "Physics.pdf")


def test_the_same_question_in_a_new_chat_on_the_same_document_is_answered_from_the_cache(
    client, ai, physics
):
    first = ask(client, study_chat(client, physics["id"])["id"]).json()
    second_chat = study_chat(client, physics["id"])["id"]

    second = ask(client, second_chat, message="what is ENTROPY?").json()

    assert len(ai.calls) == 1  # the AI was asked once
    assert (first["cached"], second["cached"]) == (False, True)
    assert second["reply"] == first["reply"]
    assert second["citations"] == first["citations"]
    assert (second["tokens_in"], second["tokens_out"]) == (0, 0)  # nothing was paid for
    saved = client.get(f"/api/conversations/{second_chat}").json()["messages"]
    assert [m["content"] for m in saved] == ["what is ENTROPY?", first["reply"]]
    assert saved[-1]["citations"] == first["citations"]


def test_other_documents_are_asked_again(client, ai, physics):
    ask(client, study_chat(client, physics["id"])["id"])
    other = upload(client, "Physics copy.pdf")

    reply = ask(client, study_chat(client, physics["id"], other["id"])["id"]).json()

    assert reply["cached"] is False
    assert len(ai.calls) == 2


def test_a_follow_up_in_the_same_chat_is_asked_again(client, ai, physics):
    chat = study_chat(client, physics["id"])["id"]
    ask(client, chat)
    calls = len(ai.calls)

    assert ask(client, chat).json()["cached"] is False  # same words, but there's history now
    assert len(ai.calls) > calls


def test_a_failed_answer_is_never_cached(client, ai, physics):
    down = FakeProvider(error=ProviderUnavailableError("down", "fake"))
    use_fakes({"main": down, "backup": down})
    assert ask(client, study_chat(client, physics["id"])["id"]).status_code == 503

    use_fakes({"main": ai, "backup": FakeProvider()})
    reply = ask(client, study_chat(client, physics["id"])["id"]).json()

    assert reply["cached"] is False and len(ai.calls) == 1


def test_a_cached_answer_is_streamed_in_one_piece(client, ai, physics):
    ask(client, study_chat(client, physics["id"])["id"])
    chat = study_chat(client, physics["id"])["id"]

    response = client.post(
        f"/api/conversations/{chat}/messages",
        json={"message": "What is entropy?"},
        headers={"accept": "text/event-stream"},
    )

    kinds = [(kind, data) for kind, data in events(response)]
    assert kinds[0] == ("token", {"text": "Entropy always increases [1]."})
    assert kinds[-1][0] == "done" and kinds[-1][1]["cached"] is True
    assert len(ai.calls) == 1


def test_each_test_starts_with_an_empty_cache(client):
    """conftest gives every test its own cache (and rate limiter): no answers leak between tests."""
    assert app.dependency_overrides[get_answer_cache]().get(key()) is None


def test_a_stopped_answer_is_never_reused(client, physics):
    """Half an answer (the Stop button) must not become the answer for next time."""
    chat = study_chat(client, physics["id"])["id"]

    def stop_now(piece_number: int) -> None:  # the Stop button, after the first word
        if piece_number == 1:
            client.post(f"/api/conversations/{chat}/stop")

    stopping = FakeProvider(replies=["Entropy always increases [1]."], before_piece=stop_now)
    use_fakes({"main": stopping, "backup": FakeProvider()})
    stream = {"accept": "text/event-stream"}
    done = events(
        client.post(
            f"/api/conversations/{chat}/messages",
            json={"message": "What is entropy?"},
            headers=stream,
        )
    )[-1][1]
    assert done["stopped"] is True

    full = FakeProvider(replies=["Entropy always increases [1]."])
    use_fakes({"main": full, "backup": FakeProvider()})
    reply = ask(client, study_chat(client, physics["id"])["id"]).json()

    assert reply["cached"] is False and len(full.calls) == 1
    assert reply["reply"] == "Entropy always increases [1]."
