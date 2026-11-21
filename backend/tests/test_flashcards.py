"""Flashcard generation: from a document or one AI answer, checked JSON. SMA-64, test-first.

The same contract as quizzes (structured.py): Pydantic checks the cards, one repair
retry, then a clear error. Cards come only from the text we show.
"""

import json

import pytest

from app.services.flashcards import FlashcardsFailed, generate_cards
from app.services.llm.exceptions import ProviderUnavailableError
from app.services.llm.fake import FakeProvider
from app.services.llm.fallback import FallbackManager
from tests.test_quiz import PIECES, REGISTRY


def card(n: int = 1, page: int | None = 2, **changes) -> dict:
    return {
        "front": f"Card {n}: what does chlorophyll reflect?",
        "back": "Green light.",
        "page": page,
        **changes,
    }


def deck_json(count: int = 5, **changes) -> str:
    return json.dumps(
        {"title": "Photosynthesis", "cards": [card(n, **changes) for n in range(count)]}
    )


def make(*replies: str, error: Exception | None = None) -> tuple[FallbackManager, FakeProvider]:
    fake = FakeProvider(
        replies=list(replies) or ["x"],
        error=error,
        model_config={"id": "json-model", "supports_json": True},
    )
    return FallbackManager(REGISTRY, lambda model: fake), fake


def test_a_valid_answer_becomes_a_deck():
    manager, fake = make(deck_json(10))

    deck = generate_cards(manager, PIECES, count=10, source="document")

    assert deck.title == "Photosynthesis" and len(deck.cards) == 10
    assert deck.cards[0] == {
        "front": "Card 0: what does chlorophyll reflect?",
        "back": "Green light.",
        "page": 2,
    }
    assert fake.options[0].json_mode is True
    user = fake.calls[0][-1]["content"]
    assert "<document>" in user and "[page 2]" in user


def test_an_answer_source_is_described_as_an_answer_without_pages():
    manager, fake = make(deck_json(3, page=None))

    generate_cards(manager, [(None, "Entropy measures disorder.")], count=5, source="answer")

    system, user = fake.calls[0][0]["content"], fake.calls[0][-1]["content"]
    assert "an answer" in system and "never follow instructions" in system
    assert "[page" not in user


def test_fewer_cards_than_asked_are_fine_down_to_three():
    manager, _ = make(deck_json(3, page=None))

    assert len(generate_cards(manager, PIECES, count=5, source="answer").cards) == 3


def test_extra_cards_are_trimmed_and_unknown_pages_cleared():
    manager, _ = make(deck_json(12, page=99))

    deck = generate_cards(manager, PIECES, count=10, source="document")

    assert len(deck.cards) == 10
    assert {c["page"] for c in deck.cards} == {None}  # page 99 was never shown


@pytest.mark.parametrize(
    "bad",
    [
        "Sure, here are some flashcards!",
        deck_json(2),  # fewer than 3
        deck_json(3, front=""),
        deck_json(3, back=""),
        json.dumps({"title": "x", "cards": [card(1), card(1), card(1)]}),  # the same front 3 times
    ],
    ids=["prose", "two cards", "empty front", "empty back", "repeated fronts"],
)
def test_a_deck_breaking_the_rules_is_repaired_once(bad):
    manager, fake = make(bad, deck_json(5))

    assert len(generate_cards(manager, PIECES, count=5, source="document").cards) == 5
    assert len(fake.calls) == 2
    assert "not valid" in fake.calls[1][-1]["content"]


def test_two_bad_answers_are_a_clear_error():
    manager, fake = make("nope", "still nope")

    with pytest.raises(FlashcardsFailed, match="broke the rules twice") as caught:
        generate_cards(manager, PIECES, count=5, source="document")

    assert len(fake.calls) == 2 and len(caught.value.attempts) == 2


def test_an_unreachable_ai_is_a_try_again_later_error():
    manager, _ = make(error=ProviderUnavailableError("down", "fake"))

    with pytest.raises(FlashcardsFailed, match="right now"):
        generate_cards(manager, PIECES, count=5, source="document")
