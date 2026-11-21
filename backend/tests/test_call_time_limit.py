"""A total time limit for one AI call (SMA-67), test-first.

Each network read already has a 60 s timeout, but a server that sends a little every 59 s
never trips it: in the SMA-51 eval, one Gemini call ran for 98 minutes. The FallbackManager
now gives every call a deadline for the WHOLE answer; past it, the call counts as timed out
(and the next model is tried, as for any timeout). Tests use a 0.2 s limit, not 90 s.
"""

import threading
import time

import pytest

from app.services.llm.base import TextStream
from app.services.llm.exceptions import AllModelsFailedError, AnswerInterruptedError
from app.services.llm.fake import FakeProvider
from app.services.llm.fallback import CALL_TIME_LIMIT_SECONDS, FallbackManager
from tests.test_fallback import MESSAGES, REGISTRY

LIMIT = 0.2


class SlowProvider(FakeProvider):
    """Answers only after `seconds`, like a server that trickles its answer."""

    def __init__(self, seconds: float, **kwargs):
        super().__init__(**kwargs)
        self.seconds = seconds

    def chat(self, messages, options=None):
        time.sleep(self.seconds)
        return super().chat(messages, options)


def manager(fakes: dict) -> FallbackManager:
    return FallbackManager(REGISTRY, lambda m: fakes[m.id], call_time_limit=LIMIT)


def test_the_real_limit_is_90_seconds():
    assert CALL_TIME_LIMIT_SECONDS == 90


def test_a_call_past_the_limit_times_out_and_the_next_model_answers():
    slow = SlowProvider(2, replies=["too late"])
    m = manager({"primary": slow, "backup": FakeProvider(replies=["in time"])})

    started = time.perf_counter()
    result = m.chat(MESSAGES, needs=["tools"])

    assert time.perf_counter() - started < 1.5  # didn't wait the 2 s
    assert result.response.text == "in time"
    assert result.fallback_used is True
    assert "primary: timed out" in result.fallback_reason
    assert [(a.model, a.status, a.error_type) for a in result.attempts] == [
        ("primary", "error", "timeout"),
        ("backup", "ok", None),
    ]


def test_when_every_model_is_too_slow_it_is_a_clear_failure():
    m = manager({"primary": SlowProvider(2), "backup": SlowProvider(2)})

    with pytest.raises(AllModelsFailedError) as failed:
        m.chat(MESSAGES, needs=["tools"])

    assert [a.error_type for a in failed.value.attempts] == ["timeout", "timeout"]


def test_a_quick_answer_is_untouched():
    m = manager({"primary": FakeProvider(replies=["quick"])})

    assert m.chat(MESSAGES, model_id="primary", allow_fallback=False).response.text == "quick"


def test_errors_inside_the_call_still_arrive_as_themselves():
    from app.services.llm.exceptions import RateLimitedError

    busy = FakeProvider(error=RateLimitedError("busy", "fake", retry_after=5))
    m = manager({"primary": busy, "backup": FakeProvider(replies=["ok"])})

    result = m.chat(MESSAGES, needs=["tools"])

    assert result.attempts[0].error_type == "rate_limited"  # not turned into a timeout


# --- Streaming: the answer stops at the deadline, and late words never arrive -----------------


def test_a_stream_past_the_limit_is_cut_off_with_what_arrived():
    shown: list[str] = []
    finished = threading.Event()

    def slow_after_two_words(number: int) -> None:
        if number == 2:
            time.sleep(0.5)  # past the deadline
        if number == 3:
            finished.set()

    slow = FakeProvider(replies=["One two three four five."], before_piece=slow_after_two_words)
    m = manager({"primary": slow, "backup": FakeProvider()})

    with pytest.raises(AnswerInterruptedError) as cut:
        m.chat(MESSAGES, needs=["tools"], stream=TextStream(on_text=shown.append))

    assert cut.value.partial_text == "One two "
    assert "timed out" in str(cut.value)
    finished.wait(2)  # the old call notices the deadline at its next word...
    time.sleep(0.1)
    assert shown == ["One ", "two "]  # ...and nothing more is shown


def test_a_stream_that_times_out_before_any_word_falls_back():
    shown: list[str] = []
    silent = FakeProvider(replies=["late words"], before_piece=lambda n: time.sleep(0.5))
    m = manager({"primary": silent, "backup": FakeProvider(replies=["Backup answer."])})

    result = m.chat(MESSAGES, needs=["tools"], stream=TextStream(on_text=shown.append))

    assert result.response.text == "Backup answer."
    time.sleep(0.6)  # the slow call wakes up: its words must not mix into this answer
    assert "".join(shown) == "Backup answer."


def test_the_stop_button_still_works_inside_the_limit():
    switch = threading.Event()
    stopping = FakeProvider(
        replies=["One two three."], before_piece=lambda n: switch.set() if n == 1 else None
    )
    m = manager({"primary": stopping})
    stream = TextStream(on_text=lambda piece: None, should_stop=switch.is_set)

    result = m.chat(MESSAGES, model_id="primary", allow_fallback=False, stream=stream)

    assert result.response.stopped is True
    assert result.response.text == "One "
