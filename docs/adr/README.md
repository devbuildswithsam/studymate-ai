# Architecture decision records (ADRs)

An ADR is a short note that records **one** important decision: the problem, what we chose,
and what that choice costs us. Code shows *what* we built; ADRs keep *why*, next to the code.

## Rules
- One decision per file, numbered: `0001-short-title.md`, `0002-...`.
- Keep it short: about one page.
- Never rewrite an accepted ADR. If a decision changes, write a new ADR that replaces it,
  and set the old one's status to `Superseded by ADR-00XX`.
- Write one when a choice is hard to undo, or when someone will later ask "why is it like this?"

## Index

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-model-ids-only-in-models-yaml.md) | Model ids live only in `models.yaml` | Accepted |
| [0002](0002-one-adapter-per-llm-provider.md) | One adapter per LLM provider behind `LLMProvider` | Accepted |
| [0003](0003-no-sdk-retries-fallback-decides.md) | No SDK retries: the FallbackManager decides | Accepted |
| [0004](0004-capability-aware-fallback.md) | Fallback is filtered by capability; config errors still fall back | Accepted |
| [0005](0005-httpx2-for-llm-http.md) | Use (and mock) `httpx2`, the HTTP client of the `openai` SDK | Accepted |
| [0006](0006-database-for-deployment.md) | Turso fails the spike: not adopted; v1.0 stays on SQLite, v1.1 database chosen then | Accepted |

## Template

Copy this into a new file:

```markdown
# ADR-00XX: <decision in a few words>

- **Status:** Proposed | Accepted | Superseded by ADR-00YY
- **Date:** YYYY-MM-DD
- **Tickets:** SMA-XX

## Context
What problem or situation forced a decision? What constraints matter?

## Decision
What we chose, in one or two sentences, then any details.

## Consequences
What becomes easier, what becomes harder, and what we must remember.

## Alternatives considered
Other options and why we didn't pick them.
```
