"""Run the evaluation against ONE real model (guide 9.5). SMA-51.

    python -m evals.run --provider groq --model openai/gpt-oss-120b
    python -m evals.run --provider gemini --model gemini-3.5-flash --pause 10

Real API calls use quota, so this runs by hand, never in CI. The documents are ingested
once into evals/.cache/eval.db (git-ignored) and reused by later runs. Every case goes
through the app's own code (retrieve, answer_from_documents, the agent loop), so the
numbers describe what a student actually gets. Only the chosen model answers (no
fallback), so models are compared fairly. Results: evals/results/<date>-<model>.csv + .md
"""

import argparse
import csv
import functools
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path

import anyio
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.conversations import MAX_OUTPUT_TOKENS, SYSTEM_PROMPT, tools_prompt
from app.config import BACKEND_DIR, get_settings
from app.db.session import _session_factory
from app.mcp_server.context import ToolContext
from app.models import Chunk, Document, Note, Task, User
from app.services.agent import run_agent_for_user
from app.services.llm.base import ChatOptions
from app.services.llm.embeddings import EmbeddingProvider, build_embedding_provider
from app.services.llm.exceptions import AllModelsFailedError, LLMError
from app.services.llm.factory import build_provider
from app.services.llm.fallback import FallbackManager, _error_type
from app.services.llm.registry import get_registry
from app.services.rag.embed import EmbeddingFailed, embed_document
from app.services.rag.ingest import ingest
from app.services.rag.retrieve import retrieve
from app.services.study import (
    CITATION,
    FULL_WIDTH_CITATION,
    TOP_K,
    StudyError,
    answer_from_documents,
)
from app.services.tool_policy import asks_to_act
from evals.scoring import (
    Case,
    hand_check_sample,
    key_facts_found,
    load_cases,
    page_spans,
    percentile,
    retrieval_scores,
    tool_call_correct,
)

EVALS = Path(__file__).resolve().parent
RATE_LIMIT_WAIT = 60  # seconds to wait once after a 429, before trying the case again
MAX_INGEST_RETRIES = 5
EVAL_EMAIL = "eval@studymate.dev"


@dataclass
class CaseResult:
    case_id: str
    kind: str
    document: str
    question: str
    answerable: bool
    answer: str = ""
    found: bool = False  # a grounded answer (not "not found")
    facts_found: int = 0
    facts_total: int = 0
    correct: bool = False  # answerable: found + every key fact; unanswerable: not found
    hit_at_5: bool | None = None  # retrieval (answerable cases only)
    reciprocal_rank: float | None = None
    citations: int = 0
    citations_correct: int = 0  # cited chunks on the expected pages of the right document
    invented_citations: int = 0  # [n] numbers that match no retrieved source
    tool_called: str = ""
    tool_arguments: str = ""
    latency_ms: int = 0
    retrieval_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    fallback_used: bool = False
    error: str = ""  # rate_limited / timeout / unavailable / config_error / error / study_error
    error_detail: str = ""  # the reason in words, e.g. "gemini-3.5-flash: rate-limited"


# --- Documents ------------------------------------------------------------------------------------


def ingest_documents(
    db: Session,
    user: User,
    documents_dir: Path,
    filenames: list[str],
    make_embedder: Callable[[], EmbeddingProvider],
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, str]:
    """{filename: document id}. A document already ready in the eval database is reused."""
    ids = {}
    for name in filenames:
        existing = db.scalar(
            select(Document).where(Document.user_id == user.id, Document.filename == name)
        )
        if existing is not None and existing.status == "ready":
            ids[name] = existing.id
            continue
        if existing is not None:  # half-done from an earlier run: start again
            db.delete(existing)
            db.commit()
        data = (documents_dir / name).read_bytes()
        document = Document(
            user_id=user.id, filename=name, mime_type="application/pdf", size_bytes=len(data)
        )
        db.add(document)
        db.commit()
        list(ingest(db, document, data, make_embedder))  # no summary: saves quota
        for _ in range(MAX_INGEST_RETRIES):  # free-tier embedding limits: wait, continue
            if document.status == "ready":
                break
            has_chunks = db.scalar(
                select(Chunk.id).where(Chunk.document_id == document.id).limit(1)
            )
            if not has_chunks:
                raise RuntimeError(f"{name} could not be ingested: {document.error}")
            sleep(RATE_LIMIT_WAIT)
            try:
                embed_document(db, document, make_embedder())
                document.status, document.error = "ready", None
                db.commit()
            except EmbeddingFailed:
                continue
        if document.status != "ready":
            raise RuntimeError(f"{name} could not be embedded: {document.error}")
        ids[name] = document.id
    return ids


# --- Cases ----------------------------------------------------------------------------------------


def run_cases(
    cases: list[Case],
    db: Session,
    user: User,
    database_url: str,
    documents: dict[str, str],
    manager: FallbackManager,
    model_id: str | None,
    make_embedder: Callable[[], EmbeddingProvider],
    today: date,
    pause: float,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = lambda line: None,
) -> list[CaseResult]:
    spans = _chunk_spans(db, list(documents.values()))
    db.execute(delete(Task).where(Task.user_id == user.id))  # tool cases start clean
    db.execute(delete(Note).where(Note.user_id == user.id))
    db.commit()
    results = []
    for number, case in enumerate(cases, start=1):
        if case.kind == "tool":
            result = _tool_case(case, user, database_url, manager, model_id, make_embedder, today)
        else:
            result = _document_case(
                case, db, user, documents, spans, manager, model_id, make_embedder, sleep
            )
        status = result.error or ("ok" if result.correct else "wrong")
        log(f"[{number}/{len(cases)}] {case.id}: {status} ({result.latency_ms} ms)")
        results.append(result)
        if pause and number < len(cases):
            sleep(pause)  # stay under the free tiers' requests-per-minute limits
    return results


def _chunk_spans(db: Session, document_ids: list[str]) -> dict[str, tuple[str, set[int]]]:
    """{chunk id: (document id, pages it covers)}, to judge retrieval and citations."""
    result = {}
    for document_id in document_ids:
        rows = db.execute(
            select(Chunk.id, Chunk.page)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index)
        ).all()
        for chunk_id, pages in page_spans([(r.id, r.page) for r in rows]).items():
            result[chunk_id] = (document_id, pages)
    return result


def _document_case(case, db, user, documents, spans, manager, model_id, make_embedder, sleep):
    result = CaseResult(
        case.id,
        "document",
        case.document,
        case.question,
        case.answerable,
        facts_total=len(case.key_facts),
    )
    expected_document = documents[case.document]

    def on_expected_pages(chunk_id: str) -> bool:
        document_id, pages = spans.get(chunk_id, ("", set()))
        return document_id == expected_document and bool(pages & set(case.expected_pages))

    all_documents = list(documents.values())  # like a study chat with all three selected
    started = time.perf_counter()
    try:
        hits = retrieve(db, user.id, case.question, make_embedder(), all_documents, top_k=TOP_K)
        result.retrieval_ms = round((time.perf_counter() - started) * 1000)
        if case.answerable:
            result.hit_at_5, result.reciprocal_rank = retrieval_scores(
                [on_expected_pages(h.chunk_id) for h in hits]
            )
        answer = _with_one_retry(
            lambda: answer_from_documents(
                db,
                user.id,
                all_documents,
                case.question,
                [],
                manager,
                model_id,
                False,
                make_embedder,
            ),
            sleep,
        )
    except (StudyError, LLMError) as e:
        result.error, result.error_detail = _classify(e), _detail(e)
        result.latency_ms = round((time.perf_counter() - started) * 1000)
        return result
    result.latency_ms = round((time.perf_counter() - started) * 1000)
    result.answer = answer.text[:600]
    result.found = answer.found
    result.tokens_in, result.tokens_out = answer.tokens_in, answer.tokens_out
    result.fallback_used = answer.fallback_used
    result.citations = len(answer.citations)
    result.citations_correct = sum(on_expected_pages(c["chunk_id"]) for c in answer.citations)
    result.invented_citations = _invented(answer.response.text)
    if case.answerable:
        result.facts_found = key_facts_found(answer.text, case.key_facts) if answer.found else 0
        result.correct = answer.found and result.facts_found == len(case.key_facts)
    else:
        result.correct = not answer.found  # it said "not found" instead of guessing
    return result


def _tool_case(case, user, database_url, manager, model_id, make_embedder, today):
    result = CaseResult(case.id, "tool", "", case.question, True)
    context = ToolContext(user.id, _session_factory(database_url), make_embedder=make_embedder)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + tools_prompt(today)},
        {"role": "user", "content": case.question},
    ]
    started = time.perf_counter()
    try:
        run = anyio.run(
            functools.partial(
                run_agent_for_user,
                context,
                manager,
                messages,
                model_id,
                False,
                ChatOptions(max_tokens=MAX_OUTPUT_TOKENS),
                user_asked_to_act=asks_to_act(case.question),
            )
        )
    except LLMError as e:
        result.error, result.error_detail = _classify(e), _detail(e)
        result.latency_ms = round((time.perf_counter() - started) * 1000)
        return result
    result.latency_ms = round((time.perf_counter() - started) * 1000)
    result.answer = run.response.text[:600]
    result.tokens_in, result.tokens_out = run.tokens_in, run.tokens_out
    result.fallback_used = run.fallback_used
    if run.steps:
        first = run.steps[0]
        result.tool_called = first.name
        result.tool_arguments = first.arguments
        try:
            arguments = json.loads(first.arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
        result.correct = tool_call_correct(
            first.name, arguments, case.expected_tool, case.expected_arguments, today
        )
    return result


def _with_one_retry(call, sleep):
    """A free-tier 429: wait a minute and try once more, then give up (recorded)."""
    try:
        return call()
    except AllModelsFailedError as e:
        if not any(a.error_type == "rate_limited" for a in e.attempts):
            raise
        sleep(RATE_LIMIT_WAIT)
        return call()


def _classify(e: Exception) -> str:
    """The same labels as llm_calls.error_type, so eval and app numbers mean the same."""
    if isinstance(e, StudyError):
        return "study_error"
    if isinstance(e, AllModelsFailedError):
        failed = [a for a in e.attempts if a.status == "error"]
        if failed:
            return failed[-1].error_type
        # No call made at all: the model was skipped while cooling down after a 429.
        return "rate_limited" if any("rate-limited" in r for r in e.reasons) else "error"
    return _error_type(e) if isinstance(e, LLMError) else "error"


def _detail(e: Exception) -> str:
    """The failure in words, kept in the CSV so a result explains itself."""
    if isinstance(e, AllModelsFailedError) and e.reasons:
        return "; ".join(e.reasons)[:300]
    return str(e)[:300]


def _invented(raw_reply: str) -> int:
    """Citation numbers in the model's raw reply that match no retrieved source."""
    text = FULL_WIDTH_CITATION.sub(r" [\1]", raw_reply)
    numbers = [int(n) for m in CITATION.findall(text) for n in re.split(r"\s*,\s*", m)]
    return sum(n < 1 or n > TOP_K for n in numbers)


# --- Results --------------------------------------------------------------------------------------


def write_results(
    results: list[CaseResult], out_dir: Path, model_id: str, provider: str, day: date
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{day.isoformat()}-{re.sub(r'[^A-Za-z0-9.]+', '-', model_id).strip('-')}"
    csv_path, md_path = out_dir / f"{stem}.csv", out_dir / f"{stem}.md"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[field.name for field in fields(CaseResult)])
        writer.writeheader()
        writer.writerows(asdict(r) for r in results)
    md_path.write_text(summary_markdown(results, model_id, provider, day), encoding="utf-8")
    return csv_path, md_path


def _share(part: int, whole: int) -> str:
    return f"{part}/{whole} ({part / whole:.0%})" if whole else "n/a"


def _check(ok: bool | None) -> str:
    return "n/a" if ok is None else ("✅" if ok else "❌")


def summary_markdown(results: list[CaseResult], model_id: str, provider: str, day: date) -> str:
    documents = [r for r in results if r.kind == "document"]
    answerable = [r for r in documents if r.answerable]
    unanswerable = [r for r in documents if not r.answerable]
    tools = [r for r in results if r.kind == "tool"]
    correct = sum(r.correct for r in answerable)
    hits = [r for r in answerable if r.hit_at_5 is not None]
    hit_count = sum(r.hit_at_5 for r in hits)
    mrr = sum(r.reciprocal_rank or 0 for r in hits) / len(hits) if hits else 0
    citations = sum(r.citations for r in documents)
    cited_ok = sum(r.citations_correct for r in documents)
    invented = sum(r.invented_citations for r in documents)
    refusals = sum(r.correct for r in unanswerable)
    false_refusals = sum(r.answerable and not r.found and not r.error for r in answerable)
    latencies = [r.latency_ms / 1000 for r in results if not r.error]
    p50, p95 = percentile(latencies, 50), percentile(latencies, 95)
    errors: dict[str, int] = {}
    for r in results:
        if r.error:
            errors[r.error] = errors.get(r.error, 0) + 1
    tools_ok = sum(r.correct for r in tools)
    big = [r for r in answerable if r.document == "french_revolution.pdf"]
    big_ok = sum(r.correct and r.citations_correct > 0 for r in big)

    def rate(part, whole):
        return part / whole if whole else None

    lines = [
        f"# Evaluation: {model_id} ({provider}), {day.isoformat()}",
        "",
        f"{len(results)} cases: {len(answerable)} answerable, {len(unanswerable)} not in the "
        f"documents, {len(tools)} tool calls. Scores are deterministic (guide 9.5); the "
        "hand-check list below is for a person.",
        "",
        "| Metric | Result | Target | Met |",
        "|---|---|---|---|",
        f"| Answer correctness (all key facts, grounded) | {_share(correct, len(answerable))} | ≥ 80% | {_check(rate(correct, len(answerable)) and rate(correct, len(answerable)) >= 0.8)} |",
        f"| Citation correctness | {_share(cited_ok, citations)} | ≥ 90% | {_check(rate(cited_ok, citations) is not None and rate(cited_ok, citations) >= 0.9)} |",
        f"| Invented citation numbers | {invented} | 0 | {_check(invented == 0)} |",
        f"| Hit rate@5 | {_share(hit_count, len(hits))} | ≥ 85% | {_check(rate(hit_count, len(hits)) is not None and rate(hit_count, len(hits)) >= 0.85)} |",
        f"| MRR | {mrr:.2f} | (higher is better) | n/a |",
        f"| Correct refusals (not in documents) | {_share(refusals, len(unanswerable))} | ≥ 90% | {_check(rate(refusals, len(unanswerable)) is not None and rate(refusals, len(unanswerable)) >= 0.9)} |",
        f"| False refusals (answerable, said not found) | {false_refusals} | as few as possible | n/a |",
        f"| Latency p50 / p95 | {p50 or 0:.1f} s / {p95 or 0:.1f} s | p95 < 10 s | {_check(p95 is not None and p95 < 10)} |",
        f"| Tokens per case (in / out, average) | {_average(results, 'tokens_in')} / {_average(results, 'tokens_out')} | known | n/a |",
        f"| Failures | {', '.join(f'{k}: {v}' for k, v in sorted(errors.items())) or 'none'} | all logged | n/a |",
        f"| Fallbacks used | {sum(r.fallback_used for r in results)} | 0 (fallback is off) | n/a |",
        f"| Tool-call correctness | {_share(tools_ok, len(tools))} | ≥ 90% | {_check(rate(tools_ok, len(tools)) is not None and rate(tools_ok, len(tools)) >= 0.9)} |",
        f"| **Stage 4 check:** 30+ page PDF, correct + cited | {_share(big_ok, len(big))} | ≥ 8/10 | {_check(big_ok >= 8 if big else None)} |",
        "",
        "## Cases",
        "",
        "| Case | Correct | Facts | Hit@5 | Cited ok | Latency | Error |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        facts = f"{r.facts_found}/{r.facts_total}" if r.facts_total else "-"
        hit = "-" if r.hit_at_5 is None else ("yes" if r.hit_at_5 else "no")
        cited = f"{r.citations_correct}/{r.citations}" if r.citations else "-"
        lines.append(
            f"| {r.case_id} | {'yes' if r.correct else 'no'} | {facts} | {hit} | {cited} | "
            f"{r.latency_ms / 1000:.1f} s | {r.error or ''} |"
        )
    sample = set(hand_check_sample([r.case_id for r in results]))
    lines += [
        "",
        "## Hand check (every 5th case, ~20%)",
        "",
        "Read each answer: is the scored result right? Tick or note what's wrong.",
        "",
    ]
    for r in results:
        if r.case_id in sample:
            answer = (r.answer or r.tool_called or r.error or "(no answer)").replace("\n", " ")
            # <br>, not two trailing spaces: pre-commit strips trailing whitespace.
            lines.append(f"- [ ] **{r.case_id}** {r.question}<br>\n  → {answer[:400]}")
    return "\n".join(lines) + "\n"


def _average(results: list[CaseResult], name: str) -> int:
    values = [getattr(r, name) for r in results if not r.error]
    return round(sum(values) / len(values)) if values else 0


# --- Command line ----------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate StudyMate with one real model.")
    parser.add_argument("--provider", required=True, help="e.g. groq or gemini (models.yaml)")
    parser.add_argument("--model", required=True, help="a model id from models.yaml")
    parser.add_argument("--pause", type=float, default=6.0, help="seconds between cases")
    parser.add_argument("--only", default="", help="comma-separated case ids, e.g. fr-01,th-02")
    args = parser.parse_args(argv)

    registry = get_registry()
    model = registry.get(args.model)
    if model.provider != args.provider:
        parser.error(f"{args.model} belongs to {model.provider}, not {args.provider}")
    settings = get_settings()
    cases = load_cases(EVALS / "cases.jsonl", EVALS / "documents")
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c.id in wanted]

    cache = EVALS / ".cache"
    cache.mkdir(exist_ok=True)
    database_url = f"sqlite:///{(cache / 'eval.db').as_posix()}"
    config = Config(BACKEND_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    db = _session_factory(database_url)()
    user = db.scalar(select(User).where(User.email == EVAL_EMAIL))
    if user is None:
        user = User(email=EVAL_EMAIL, name="Evaluation")
        db.add(user)
        db.commit()

    embedder = build_embedding_provider(registry, settings)
    filenames = sorted({c.document for c in cases if c.document})
    print(f"Ingesting {len(filenames)} documents (reused if already in {cache})...")
    documents = ingest_documents(db, user, EVALS / "documents", filenames, lambda: embedder)
    manager = FallbackManager(registry, lambda m: build_provider(m, registry, settings))
    print(f"Running {len(cases)} cases with {args.model}...")
    today = date.today()
    results = run_cases(
        cases,
        db,
        user,
        database_url,
        documents,
        manager,
        args.model,
        lambda: embedder,
        today=today,
        pause=args.pause,
        log=print,
    )
    csv_path, md_path = write_results(results, EVALS / "results", args.model, args.provider, today)
    print(f"Wrote {csv_path} and {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
