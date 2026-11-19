"""The evaluation's scoring: deterministic, so a run can be compared with the next one
(guide 9.5). SMA-51, test-first. No AI here: these are plain functions.
"""

from datetime import date
from pathlib import Path

import pytest

from evals.scoring import (
    CaseError,
    hand_check_sample,
    key_facts_found,
    load_cases,
    normalise,
    page_spans,
    percentile,
    retrieval_scores,
    tool_call_correct,
)

EVALS = Path(__file__).resolve().parents[1] / "evals"


# --- The test set ------------------------------------------------------------------------------


def test_the_committed_test_set_is_valid():
    cases = load_cases(EVALS / "cases.jsonl", EVALS / "documents")

    assert len(cases) == 30
    documents = [c for c in cases if c.kind == "document"]
    unanswerable = [c for c in documents if not c.answerable]
    assert 0.15 <= len(unanswerable) / len(documents) <= 0.25  # guide: ~20% "not in document"
    assert sum(c.document == "french_revolution.pdf" and c.answerable for c in documents) == 10
    assert {c.kind for c in cases} == {"document", "tool"}


def write_cases(tmp_path, *lines: str) -> Path:
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "a.pdf").write_bytes(b"%PDF-")
    return path


@pytest.mark.parametrize(
    "line, problem",
    [
        (
            '{"id": "x", "document": "missing.pdf", "question": "q", "answerable": false}',
            "missing.pdf",
        ),
        ('{"id": "x", "document": "a.pdf", "question": "q", "answerable": true}', "key facts"),
        (
            '{"id": "x", "document": "a.pdf", "question": "q", "answerable": true, "key_facts": [["f"]]}',
            "pages",
        ),
        ('{"id": "x", "kind": "tool", "question": "q"}', "expected_tool"),
    ],
    ids=[
        "unknown document",
        "answerable without facts",
        "answerable without pages",
        "tool without tool",
    ],
)
def test_a_broken_case_is_refused_with_the_reason(tmp_path, line, problem):
    with pytest.raises(CaseError, match=problem):
        load_cases(write_cases(tmp_path, line), tmp_path / "docs")


def test_case_ids_must_be_unique(tmp_path):
    line = '{"id": "x", "document": "a.pdf", "question": "q", "answerable": false}'

    with pytest.raises(CaseError, match="duplicate"):
        load_cases(write_cases(tmp_path, line, line), tmp_path / "docs")


# --- Answer correctness: key facts --------------------------------------------------------------


def test_each_key_fact_counts_when_any_spelling_is_present():
    facts = [["14 July", "July 14"], ["1789"], ["Bastille"]]

    assert key_facts_found("The Bastille fell on July 14, 1789.", facts) == 3
    assert key_facts_found("It fell in 1789.", facts) == 1


def test_matching_ignores_case_accents_and_odd_spaces():
    # Seen in real answers: narrow no-break spaces (U+202F) and accents (Sieyès).
    assert normalise("Sieyès and  DUCOS") == "sieyes and ducos"
    assert key_facts_found("in 1789 with Sieyès", [["1789"], ["Sieyes"]]) == 2


# --- Retrieval: hit rate @5 and MRR ---------------------------------------------------------------


def test_a_chunk_covers_the_pages_until_the_next_chunk_starts():
    spans = page_spans([("c1", 1), ("c2", 1), ("c3", 4), ("c4", 7)])

    assert spans == {"c1": {1}, "c2": {1, 2, 3, 4}, "c3": {4, 5, 6, 7}, "c4": {7}}


@pytest.mark.parametrize(
    "relevant, hit, reciprocal_rank",
    [
        ([True, False, False], True, 1.0),
        ([False, False, True], True, 1 / 3),
        ([False, False, False, False, False, True], False, 0.0),  # 6th place is outside the top 5
        ([], False, 0.0),
    ],
)
def test_hit_rate_and_reciprocal_rank(relevant, hit, reciprocal_rank):
    assert retrieval_scores(relevant) == (hit, pytest.approx(reciprocal_rank))


# --- Latency percentiles ---------------------------------------------------------------------------


def test_percentiles_use_the_nearest_rank():
    values = [1.0, 2.0, 3.0, 4.0, 10.0]

    assert percentile(values, 50) == 3.0
    assert percentile(values, 95) == 10.0
    assert percentile([], 50) is None


# --- Tool calls -------------------------------------------------------------------------------------


def test_create_task_by_friday_needs_the_next_friday():
    wednesday = date(2026, 11, 18)
    expected = {"title_contains": "chapter 3", "due_date": "next friday"}

    good = {"title": "Revise chapter 3 notes", "due_date": "2026-11-20"}
    assert tool_call_correct("create_task", good, "create_task", expected, wednesday)
    wrong_day = {"title": "Revise chapter 3 notes", "due_date": "2026-11-21"}
    assert not tool_call_correct("create_task", wrong_day, "create_task", expected, wednesday)
    week_late = {"title": "Revise chapter 3 notes", "due_date": "2026-11-27"}  # not THIS Friday
    assert not tool_call_correct("create_task", week_late, "create_task", expected, wednesday)
    wrong_title = {"title": "Physics", "due_date": "2026-11-20"}
    assert not tool_call_correct("create_task", wrong_title, "create_task", expected, wednesday)


def test_on_a_friday_today_or_next_week_both_count():
    friday = date(2026, 11, 20)
    expected = {"due_date": "next friday"}

    assert tool_call_correct(
        "create_task", {"due_date": "2026-11-20"}, "create_task", expected, friday
    )
    assert tool_call_correct(
        "create_task", {"due_date": "2026-11-27"}, "create_task", expected, friday
    )


def test_the_wrong_tool_or_no_tool_is_wrong():
    assert not tool_call_correct("list_tasks", {}, "create_task", {}, date(2026, 11, 18))
    assert not tool_call_correct(None, {}, "list_tasks", {}, date(2026, 11, 18))
    assert tool_call_correct("list_tasks", {"status": "todo"}, "list_tasks", {}, date(2026, 11, 18))


# --- The hand-check sample ---------------------------------------------------------------------------


def test_every_fifth_case_is_marked_for_a_hand_check():
    ids = [f"c{n}" for n in range(1, 31)]

    sample = hand_check_sample(ids)

    assert sample == ["c5", "c10", "c15", "c20", "c25", "c30"]  # 20%, the same every run
