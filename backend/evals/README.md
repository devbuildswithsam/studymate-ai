# Evaluation (SMA-51, guide 9.5)

Measures how well StudyMate answers questions about documents, with **real** models.
Real API calls use free quota, so this runs **by hand**, never in CI (CI runs the normal
tests, which use fakes only).

```bat
cd backend
.venv\Scripts\activate
python -m evals.run --provider groq --model openai/gpt-oss-120b --pause 30
python -m evals.run --provider gemini --model gemini-3.5-flash --pause 30
python -m evals.run --provider groq --model openai/gpt-oss-120b --only fr-01,th-02
```

`--pause` waits between cases to stay under the free tiers' per-minute limits; a 429 is
waited out once (60 s) and then recorded as a failure.

## What's here

| Path | What |
|---|---|
| `documents/` | 3 Wikipedia articles as PDFs, frozen (see `ATTRIBUTION.md`, CC BY-SA 4.0) |
| `cases.jsonl` | 30 cases: 22 answerable questions with key facts and pages, 5 "not in the documents", 3 tool calls |
| `scoring.py` | deterministic scoring (unit-tested in `tests/test_evals_scoring.py`) |
| `run.py` | runs every case through the app's own code and writes the results |
| `results/` | `<date>-<model>.csv` (one row per case) and `.md` (the summary) |
| `.cache/eval.db` | the ingested documents, reused by later runs (git-ignored) |

## How it scores (the same every run)

- **Answer correctness:** an answerable case is correct when the answer is grounded (found
  in the documents) **and** contains every key fact (any listed spelling; case, accents and
  spaces ignored).
- **Citations:** a citation is correct when its chunk is in the expected document and covers
  an expected page. Invented numbers (no matching source) are counted separately.
- **Retrieval:** hit rate@5 (a chunk on an expected page is in the top 5) and MRR, measured
  before the model is called.
- **Refusals:** a "not in the documents" case passes when the answer is "not found".
- **Latency** p50 / p95, **tokens**, **failures** (same labels as `llm_calls`), **fallbacks**
  (off: only the chosen model answers), **tool calls** (right tool + arguments).
- **Stage 4 check:** of the 10 answerable questions on the 39-page French Revolution PDF, at
  least 8 correct **and** cited.

Every question asks across all three documents (like a study chat with all of them picked),
so retrieval must also find the right document.

**Hand check:** the summary lists every 5th case (~20%). Read those answers and tick them:
an automatic score is only as good as its key facts. An LLM judge could be added as an extra
signal later, never as the final score.

## Adding cases

One JSON object per line. A document case needs `id`, `document`, `question`, `answerable`;
answerable ones also need `key_facts` (a list of facts, each a list of accepted spellings)
and `expected_pages`. A tool case needs `kind: "tool"`, `expected_tool` and optional
`expected_arguments` (`title_contains`, `due_date: "next friday"`). `load_cases` refuses a
broken file with the reason.
