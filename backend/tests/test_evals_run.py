"""The evaluation runner, end to end with FAKE AI (the real runs are manual: guide 9.5).
SMA-51. Proves the harness works: real PDFs are ingested, cases run through the app's own
code, results are scored and written as CSV + Markdown.
"""

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from app.db.session import _session_factory
from app.models import User
from app.services.llm.base import ToolCall
from app.services.llm.fake import FakeEmbeddingProvider, FakeProvider
from app.services.llm.fallback import FallbackManager
from evals.run import ingest_documents, run_cases, write_results
from evals.scoring import load_cases
from tests.tool_helpers import REGISTRY

EVALS = Path(__file__).resolve().parents[1] / "evals"


@pytest.fixture
def eval_db(db_url):
    session = _session_factory(db_url)()
    user = User(email="eval@studymate.dev")
    session.add(user)
    session.commit()
    yield session, user, db_url
    session.close()


def test_a_run_scores_cases_and_writes_csv_and_markdown(eval_db, tmp_path):
    db, user, db_url = eval_db
    cases = [
        c
        for c in load_cases(EVALS / "cases.jsonl", EVALS / "documents")
        if c.id in ("fr-01", "tool-02")
    ]
    embedder = FakeEmbeddingProvider()
    documents = ingest_documents(
        db, user, EVALS / "documents", ["french_revolution.pdf"], lambda: embedder
    )
    model = FakeProvider(
        replies=[
            "The Bastille was stormed on 14 July 1789 [1].",  # fr-01
            [ToolCall("c1", "list_tasks", json.dumps({"status": "todo"}))],  # tool-02
            "You have no pending tasks.",
        ]
    )
    manager = FallbackManager(REGISTRY, lambda m: model)

    results = run_cases(
        cases,
        db,
        user,
        db_url,
        documents,
        manager,
        "tools-model",
        lambda: embedder,
        today=date(2026, 11, 18),
        pause=0,
    )

    by_id = {r.case_id: r for r in results}
    assert by_id["fr-01"].found and by_id["fr-01"].facts_found == 2 and by_id["fr-01"].correct
    assert by_id["fr-01"].error == ""
    assert by_id["tool-02"].tool_called == "list_tasks" and by_id["tool-02"].correct

    csv_path, md_path = write_results(results, tmp_path, "tools-model", "p", date(2026, 11, 18))

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert [r["case_id"] for r in rows] == ["fr-01", "tool-02"]
    summary = md_path.read_text(encoding="utf-8")
    assert "Answer correctness" in summary and "Hit rate@5" in summary and "Hand check" in summary
    assert csv_path.name == "2026-11-18-tools-model.csv"


def test_documents_are_ingested_once_and_reused(eval_db):
    db, user, _ = eval_db
    embedder = FakeEmbeddingProvider()

    first = ingest_documents(
        db, user, EVALS / "documents", ["thermodynamics.pdf"], lambda: embedder
    )
    calls = len(embedder.batches)
    again = ingest_documents(
        db, user, EVALS / "documents", ["thermodynamics.pdf"], lambda: embedder
    )

    assert first == again
    assert len(embedder.batches) == calls  # no new embedding calls: quota saved


def test_a_failing_case_is_recorded_not_fatal(eval_db):
    db, user, db_url = eval_db
    cases = [c for c in load_cases(EVALS / "cases.jsonl", EVALS / "documents") if c.id == "th-02"]
    embedder = FakeEmbeddingProvider()
    documents = ingest_documents(
        db, user, EVALS / "documents", ["thermodynamics.pdf"], lambda: embedder
    )
    from app.services.llm.exceptions import ProviderTimeoutError

    manager = FallbackManager(
        REGISTRY, lambda m: FakeProvider(error=ProviderTimeoutError("slow", "p"))
    )

    [result] = run_cases(
        cases,
        db,
        user,
        db_url,
        documents,
        manager,
        "tools-model",
        lambda: embedder,
        today=date(2026, 11, 18),
        pause=0,
    )

    assert result.error == "timeout" and result.correct is False


def test_a_rate_limit_cooldown_is_labelled_rate_limited_with_the_reason():
    # Seen in the first Gemini run: after a 429 the manager skips the model while it cools
    # down, so later cases fail with no attempt at all. That is a rate limit, not "error".
    from app.services.llm.exceptions import AllModelsFailedError
    from evals.run import _classify, _detail

    cooling = AllModelsFailedError(
        "All models failed", reasons=["gemini-3.5-flash: rate-limited (cooling down)"], attempts=[]
    )

    assert _classify(cooling) == "rate_limited"
    assert "cooling down" in _detail(cooling)


def test_a_failed_case_records_why(eval_db):
    db, user, db_url = eval_db
    cases = [c for c in load_cases(EVALS / "cases.jsonl", EVALS / "documents") if c.id == "th-02"]
    embedder = FakeEmbeddingProvider()
    documents = ingest_documents(
        db, user, EVALS / "documents", ["thermodynamics.pdf"], lambda: embedder
    )
    from app.services.llm.exceptions import ProviderUnavailableError

    manager = FallbackManager(
        REGISTRY, lambda m: FakeProvider(error=ProviderUnavailableError("503 overloaded", "p"))
    )

    [result] = run_cases(
        cases,
        db,
        user,
        db_url,
        documents,
        manager,
        "tools-model",
        lambda: embedder,
        today=date(2026, 11, 18),
        pause=0,
    )

    assert result.error == "unavailable"
    assert "unavailable" in result.error_detail


def test_the_summary_has_no_trailing_spaces():
    # pre-commit's trailing-whitespace hook strips them (and a Markdown line break with them).
    from evals.run import CaseResult, summary_markdown

    results = [
        CaseResult(f"c{n}", "document", "a.pdf", "Question?", True, answer="An answer.")
        for n in range(1, 6)
    ]

    text = summary_markdown(results, "m", "p", date(2026, 11, 19))

    assert not any(line.endswith(" ") for line in text.splitlines())
    assert "**c5** Question?<br>" in text
