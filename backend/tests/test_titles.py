"""Conversation titles: a short AI title, or the first words if the AI can't. SMA-31.

The AI is always a FakeProvider: no real API is called.
"""

import pytest

from app.services.llm.exceptions import ProviderUnavailableError, RateLimitedError
from app.services.llm.fake import FakeProvider
from app.services.llm.fallback import FallbackManager
from app.services.llm.registry import ModelRegistry
from app.services.titles import (
    TITLE_MAX_TOKENS,
    clean_title,
    fallback_title,
    generate_title,
)

REGISTRY = ModelRegistry.model_validate(
    {
        "version": 1,
        "providers": {"p": {"base_url": "https://p.test/v1", "api_key_env": "P_KEY"}},
        "models": [
            {"id": "main", "provider": "p", "display_name": "Main", "priority": 1},
            {"id": "backup", "provider": "p", "display_name": "Backup", "priority": 2},
        ],
    }
)


def manager_with(main: FakeProvider, backup: FakeProvider | None = None) -> FallbackManager:
    fakes = {
        "main": main,
        "backup": backup or FakeProvider(error=ProviderUnavailableError("x", "p")),
    }
    return FallbackManager(REGISTRY, lambda m: fakes[m.id])


# --- Fallback: the first few words -------------------------------------------------


def test_a_short_message_is_its_own_title():
    assert fallback_title("Explain osmosis") == "Explain osmosis"


def test_a_long_message_keeps_its_first_six_words():
    title = fallback_title("What is osmosis and why does it matter for plant roots?")

    assert title == "What is osmosis and why does…"


def test_line_breaks_and_extra_spaces_are_flattened():
    assert fallback_title("  Explain\n\nNewton's   laws  ") == "Explain Newton's laws"


def test_one_giant_word_is_cut_to_60_characters():
    title = fallback_title("x" * 500)

    assert len(title) == 60
    assert title.endswith("…")


# --- Cleaning what the AI wrote ----------------------------------------------------


@pytest.mark.parametrize(
    "raw, clean",
    [
        ("Osmosis in Plant Roots", "Osmosis in Plant Roots"),
        ('"Osmosis in Plant Roots."', "Osmosis in Plant Roots"),  # quotes and full stop
        ("**Title:** Osmosis Basics", "Osmosis Basics"),  # Markdown and a label
        ("Osmosis Basics\nThis chat explains...", "Osmosis Basics"),  # first line only
        ("   ", None),  # nothing usable
        ("", None),
    ],
)
def test_clean_title(raw, clean):
    assert clean_title(raw) == clean


def test_a_too_long_ai_title_is_cut_at_a_word():
    title = clean_title("An Extremely Detailed Exploration of " + "Osmosis " * 10)

    assert len(title) <= 60
    assert title.endswith("…")
    assert not title[:-1].endswith(" ")  # cut between words, not inside one


# --- generate_title ----------------------------------------------------------------


def test_the_ai_title_is_used_and_the_call_is_reported():
    main = FakeProvider(replies=['"Osmosis in Plant Roots."'])

    result = generate_title(manager_with(main), "What is osmosis?", model_id="main")

    assert result.title == "Osmosis in Plant Roots"
    assert [(a.model, a.status) for a in result.attempts] == [("main", "ok")]


def test_the_ai_gets_a_short_instruction_and_room_to_think():
    main = FakeProvider(replies=["Osmosis"])

    generate_title(manager_with(main), "What is osmosis? " * 100, model_id="main")

    system, user = main.calls[0]
    assert system["role"] == "system" and "title" in system["content"].lower()
    assert len(user["content"]) <= 500  # only the start of a long first message is sent
    # Thinking models spend tokens before writing; 20-60 gave empty answers (SMA-31 probe).
    assert main.options[0].max_tokens == TITLE_MAX_TOKENS == 300


def test_it_falls_back_to_the_next_model():
    main = FakeProvider(error=RateLimitedError("429", "p"))
    backup = FakeProvider(replies=["Osmosis Basics"])

    result = generate_title(manager_with(main, backup), "What is osmosis?", model_id="main")

    assert result.title == "Osmosis Basics"
    assert [a.status for a in result.attempts] == ["error", "ok"]


def test_when_every_model_fails_the_first_words_are_used():
    main = FakeProvider(error=RateLimitedError("429", "p"))

    result = generate_title(manager_with(main), "Explain the Krebs cycle step by step please")

    assert result.title == "Explain the Krebs cycle step by…"
    assert [a.status for a in result.attempts] == ["error", "error"]  # still logged


def test_an_unusable_ai_answer_falls_back_to_the_first_words():
    main = FakeProvider(replies=['""'])

    result = generate_title(manager_with(main), "Explain entropy", model_id="main")

    assert result.title == "Explain entropy"
