"""Deterministic scoring for the evaluation (guide 9.5). SMA-51.

Plain functions, no AI: the same answer always gets the same score, so runs (and models)
can be compared. An LLM judge could be an extra signal later, never the final score.
"""

import json
import math
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError, model_validator


class CaseError(Exception):
    """cases.jsonl has a mistake; the message names the case and the problem."""


class Case(BaseModel):
    id: str
    kind: Literal["document", "tool"] = "document"
    question: str
    # Document questions:
    document: str | None = None  # a file in evals/documents/
    answerable: bool = True  # False: the right answer is "not found in your documents"
    key_facts: list[list[str]] = []  # each fact: accepted spellings; ALL facts = correct
    expected_pages: list[int] = []  # where the answer is
    # Tool questions:
    expected_tool: str | None = None
    expected_arguments: dict[str, Any] = {}

    @model_validator(mode="after")
    def check(self) -> "Case":
        if self.kind == "tool":
            if not self.expected_tool:
                raise ValueError("a tool case needs expected_tool")
            return self
        if not self.document:
            raise ValueError("a document case needs a document")
        if self.answerable and not self.key_facts:
            raise ValueError("an answerable case needs key facts")
        if self.answerable and not self.expected_pages:
            raise ValueError("an answerable case needs expected pages")
        return self


def load_cases(path: Path, documents_dir: Path) -> list[Case]:
    cases = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = Case.model_validate(json.loads(line))
        except (json.JSONDecodeError, ValidationError) as e:
            raise CaseError(f"{path.name} line {number}: {e}") from e
        if case.document and not (documents_dir / case.document).exists():
            raise CaseError(f"{case.id}: document {case.document} is not in {documents_dir}")
        cases.append(case)
    ids = [c.id for c in cases]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise CaseError(f"duplicate case ids: {duplicates}")
    return cases


# --- Answer correctness ---------------------------------------------------------------------------


def normalise(text: str) -> str:
    """Lower case, no accents, one kind of space and dash: "Sieyès" matches "Sieyes"."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[‐-―−]", "-", text)  # all dashes -> "-"
    text = re.sub(r"\s+", " ", text)  # includes no-break and narrow spaces
    return text.lower().strip()


def key_facts_found(answer: str, key_facts: list[list[str]]) -> int:
    """How many key facts the answer contains (a fact counts if ANY spelling is there)."""
    text = normalise(answer)
    return sum(any(normalise(spelling) in text for spelling in fact) for fact in key_facts)


# --- Retrieval ------------------------------------------------------------------------------------


def page_spans(chunks: list[tuple[str, int | None]]) -> dict[str, set[int]]:
    """Pages each chunk covers: from its own start page to where the next chunk starts.

    `chunks` is one document's (chunk id, start page), in reading order. A chunk only
    stores the page it STARTS on, but it can run onto the following pages.
    """
    spans: dict[str, set[int]] = {}
    for i, (chunk_id, page) in enumerate(chunks):
        if page is None:
            spans[chunk_id] = set()
            continue
        next_start = chunks[i + 1][1] if i + 1 < len(chunks) else page
        spans[chunk_id] = set(range(page, max(page, next_start or page) + 1))
    return spans


def retrieval_scores(relevant: list[bool], k: int = 5) -> tuple[bool, float]:
    """(hit@k, reciprocal rank) for one question, from the ranked results' relevance.

    hit@k: a relevant chunk is in the top k. Reciprocal rank: 1/position of the first
    relevant chunk (1 = first place, 0.5 = second...), 0 if none: averaged, that's MRR.
    """
    hit = any(relevant[:k])
    first = next((i for i, r in enumerate(relevant) if r), None)
    return hit, (1 / (first + 1) if first is not None and first < k else 0.0)


# --- Latency ---------------------------------------------------------------------------------------


def percentile(values: list[float], p: float) -> float | None:
    """The nearest-rank percentile: p95 = the value 95% of the results are at or below."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


# --- Tool calls -------------------------------------------------------------------------------------


def tool_call_correct(
    called: str | None,
    arguments: dict[str, Any],
    expected_tool: str,
    expected: dict[str, Any],
    today: date,
) -> bool:
    """The right tool, with arguments that match what the case expects."""
    if called != expected_tool:
        return False
    if "title_contains" in expected:
        if expected["title_contains"].lower() not in str(arguments.get("title", "")).lower():
            return False
    if expected.get("due_date") == "next friday":
        if arguments.get("due_date") not in {d.isoformat() for d in _fridays(today)}:
            return False
    return True


def _fridays(today: date) -> list[date]:
    """'By Friday': the coming Friday. On a Friday, today or next week both make sense."""
    ahead = (4 - today.weekday()) % 7  # Monday = 0, Friday = 4
    coming = today + timedelta(days=ahead)
    return [coming, coming + timedelta(days=7)] if ahead == 0 else [coming]


# --- Hand check ---------------------------------------------------------------------------------------


def hand_check_sample(case_ids: list[str]) -> list[str]:
    """Every fifth case (20%), the same ones every run: you check these answers by hand."""
    return [case_id for i, case_id in enumerate(case_ids, start=1) if i % 5 == 0]
