"""Ask the AI for JSON, check it, repair once (guide Stage 5 "Structured outputs").

Shared by quizzes (SMA-63) and flashcards (SMA-64): one copy of the loop, so a fix to it
helps both. The caller gives a `check` that turns the reply into checked data or raises
ValueError with a short reason; a bad first reply gets ONE retry that shows the model its
own reply and that reason ("repair"). One retry only: the free quota is precious.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.services.llm.base import ChatOptions, Message
from app.services.llm.exceptions import LLMError
from app.services.llm.fallback import Attempt, FallbackManager
from app.services.summary import document_excerpt

PAGE_LABEL = re.compile(r"\[page (\d+)\]")


@dataclass
class DocumentBlock:
    """A source as the model sees it: inside <document> tags, labelled with its pages."""

    text: str  # "<document>\n[page 1]\n...\n</document>", with a note if excerpted
    shown_pages: set[int]  # the pages whose labels the model saw: the only valid sources
    has_pages: bool  # False for TXT / MD and AI answers: no "[page N]" labels at all


def document_block(pieces: list[tuple[int | None, str]]) -> DocumentBlock:
    """The chunks (page, text) labelled "[page N]"; long sources become evenly spaced
    excerpts (summary.py). Inside tags: the source is reference material, never commands."""
    labelled = [f"[page {page}]\n{text}" if page is not None else text for page, text in pieces]
    text, partial = document_excerpt(labelled)
    note = "These are evenly spaced excerpts of a longer document.\n" if partial else ""
    return DocumentBlock(
        text=f"{note}<document>\n{text}\n</document>",
        shown_pages={int(n) for n in PAGE_LABEL.findall(text)},
        has_pages=any(page is not None for page, _ in pieces),
    )


class StructuredFailed(Exception):
    """No valid answer. `unavailable`: the AI couldn't be reached (busy, down); otherwise
    it answered twice, and broke the rules twice. Every call made is in `attempts`."""

    def __init__(self, reason: str, attempts: list[Attempt], unavailable: bool):
        super().__init__(reason)
        self.attempts = attempts
        self.unavailable = unavailable


def parse_as[M: BaseModel](model: type[M], reply: str) -> M:
    """The reply as a checked `model`, or ValueError with a reason the AI can act on."""
    try:
        return model.model_validate(json.loads(reply))
    except json.JSONDecodeError:
        raise ValueError("it was not JSON") from None
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        raise ValueError(f"{where}: {first['msg']}") from None


def ask_for_json[T](
    manager: FallbackManager,
    messages: list[Message],
    options: ChatOptions,
    check: Callable[[str], T],
    repair_note: Callable[[str], str],  # the reason -> what to tell the model
    model_id: str | None = None,
) -> tuple[T, list[Attempt]]:
    messages = list(messages)  # the repair turn is added to our copy only
    attempts: list[Attempt] = []
    for try_number in (1, 2):
        try:
            # needs=("json",): never fall back to a model that can't promise JSON.
            result = manager.chat(messages, options, model_id, needs=("json",))
        except LLMError as e:
            raise StructuredFailed(str(e), attempts + getattr(e, "attempts", []), True) from e
        attempts += result.attempts
        reply = result.response.text
        try:
            return check(reply), attempts
        except ValueError as problem:
            if try_number == 2:
                raise StructuredFailed(str(problem), attempts, False) from None
            # The repair: show the model its own reply and exactly what was wrong with it.
            messages += [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": repair_note(str(problem))},
            ]
    raise AssertionError("unreachable")  # the loop always returns or raises
