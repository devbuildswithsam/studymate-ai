"""Per-user rate limits (SMA-67), test-first.

A "sliding window": at most N actions in any 60 seconds, per user and per kind of action.
Over the limit -> 429 with a friendly message and a Retry-After header (in seconds).
Counted in memory, like the login limiter (one server process in v1.1).
"""

import json

import pytest

from app.main import app
from app.services.llm.exceptions import ProviderUnavailableError
from app.services.llm.fake import FakeProvider
from app.services.rate_limits import LIMITS, RateLimiter, get_rate_limiter
from tests.pdf_maker import make_pdf
from tests.test_conversations_api import new_conversation, use_fakes


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


# --- The limiter on its own -------------------------------------------------------------------


def test_the_limits_from_the_ticket():
    assert LIMITS == {"chat": (20, 60), "upload": (5, 60), "generate": (5, 60)}


def test_up_to_the_limit_then_refused_with_when_to_retry(clock):
    limiter = RateLimiter({"chat": (3, 60)}, clock)

    for _ in range(3):
        assert limiter.hit("alice", "chat") is None  # None = allowed
        clock.now += 10

    # The first of the 3 was 30 s ago: it leaves the window in 30 s.
    assert limiter.hit("alice", "chat") == 30


def test_the_window_slides_and_the_limit_resets(clock):
    limiter = RateLimiter({"chat": (2, 60)}, clock)
    limiter.hit("alice", "chat")
    limiter.hit("alice", "chat")
    assert limiter.hit("alice", "chat") is not None

    clock.now += 60  # a minute later, both have left the window

    assert limiter.hit("alice", "chat") is None


def test_refused_attempts_do_not_count(clock):
    limiter = RateLimiter({"chat": (1, 60)}, clock)
    limiter.hit("alice", "chat")
    for _ in range(5):
        limiter.hit("alice", "chat")  # refused: must not push the reset further away

    clock.now += 60

    assert limiter.hit("alice", "chat") is None


def test_each_user_and_each_kind_has_its_own_count(clock):
    limiter = RateLimiter({"chat": (1, 60), "upload": (1, 60)}, clock)
    limiter.hit("alice", "chat")

    assert limiter.hit("alice", "chat") is not None
    assert limiter.hit("bob", "chat") is None  # Alice's messages never slow Bob down
    assert limiter.hit("alice", "upload") is None  # chatting doesn't use up uploads


def test_retry_after_is_at_least_one_second(clock):
    limiter = RateLimiter({"chat": (1, 60)}, clock)
    limiter.hit("alice", "chat")
    clock.now += 59.9

    assert limiter.hit("alice", "chat") == 1  # never "retry in 0 seconds"


# --- Through the API ------------------------------------------------------------------------


@pytest.fixture
def limiter(client, clock) -> RateLimiter:
    """Small limits so the tests stay quick, on a clock we move by hand."""
    limiter = RateLimiter({"chat": (2, 60), "upload": (2, 60), "generate": (1, 60)}, clock)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    return limiter


def assert_rate_limited(response, retry_after: int, words: str) -> None:
    assert response.status_code == 429, response.text
    error = response.json()["error"]
    assert error["code"] == "rate_limited"
    assert words in error["message"]
    assert f"{retry_after} seconds" in error["message"]
    assert response.headers["retry-after"] == str(retry_after)


def test_too_many_chat_messages_get_429_and_the_ai_is_not_asked(client, limiter, clock):
    fake = FakeProvider(replies=["Hi."])
    use_fakes({"main": fake, "backup": FakeProvider()})
    chat = new_conversation(client)

    def send():
        return client.post(f"/api/conversations/{chat}/messages", json={"message": "Hi"})

    assert send().status_code == 200
    clock.now += 15
    assert send().status_code == 200
    refused = send()

    assert_rate_limited(refused, 45, "messages")
    assert len(fake.calls) == 2  # the refused message never reached the AI
    clock.now += 45
    assert send().status_code == 200  # the reset


def test_a_streamed_message_is_limited_too(client, limiter):
    use_fakes({"main": FakeProvider(replies=["Hi."]), "backup": FakeProvider()})
    chat = new_conversation(client)
    stream = {"accept": "text/event-stream"}
    for _ in range(2):
        client.post(f"/api/conversations/{chat}/messages", json={"message": "Hi"}, headers=stream)

    refused = client.post(
        f"/api/conversations/{chat}/messages", json={"message": "Hi"}, headers=stream
    )

    assert_rate_limited(refused, 60, "messages")  # a normal 429, before any stream starts


def upload(client, name: str):
    pdf = make_pdf(["Entropy always increases in an isolated system."])
    return client.post("/api/documents", files={"file": (name, pdf, "application/pdf")})


def test_too_many_uploads_get_429(client, limiter):
    assert upload(client, "a.pdf").status_code == 201
    assert upload(client, "b.pdf").status_code == 201

    assert_rate_limited(upload(client, "c.pdf"), 60, "uploads")


def test_quizzes_and_flashcards_share_one_generation_limit(client, limiter):
    document = json.loads(upload(client, "a.pdf").text.splitlines()[-1])["document"]
    down = FakeProvider(error=ProviderUnavailableError("down", "fake"))
    use_fakes({"main": down, "backup": down})
    first = client.post("/api/quizzes", json={"document_id": document["id"], "questions": 5})
    assert first.status_code == 503  # it failed, but it still asked the AI: it counts

    refused = client.post("/api/decks", json={"document_id": document["id"]})

    assert_rate_limited(refused, 60, "quizzes or flashcards")


def test_regenerating_a_summary_is_a_generation_too(client, limiter):
    document = json.loads(upload(client, "a.pdf").text.splitlines()[-1])["document"]
    summary = f"/api/documents/{document['id']}/summary"

    assert client.post(summary, json={}).status_code == 200  # conftest's fake AI writes it

    assert_rate_limited(client.post(summary, json={}), 60, "quizzes or flashcards")
