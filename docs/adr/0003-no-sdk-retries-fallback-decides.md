# ADR-0003: No SDK retries — the FallbackManager decides

- **Status:** Accepted
- **Date:** 2026-11-15
- **Tickets:** SMA-21, SMA-22

## Context
By default the `openai` SDK quietly retries a failed request twice, with waits in between.
For us that would:
- hide HTTP 429s, so we could not learn that a model is rate-limited and switch;
- make a failing provider take much longer before we try the next model;
- spread "what to do on failure" across two places (the SDK and our own code).

CLAUDE.md asks us to handle 404 (fix config), 429 (wait / fall back) and 503
(retry / fall back) differently, which needs one place that sees every failure.

## Decision
The adapters create the client with `max_retries=0` (`openai_compat.py`). An adapter tries
once and immediately raises one of our error types. All decisions — skip, wait, fall back,
or give up — are made by the `FallbackManager` (`fallback.py`).

The dev scripts in `backend/scripts/` are not part of the app and keep the SDK default
(`client_for(..., max_retries=2)`).

## Consequences
- Failures surface fast, and the FallbackManager can label the answer
  ("answered by Groq because Gemini was rate-limited").
- After a 429 the manager skips that model for `retry_after` seconds (60 if not given),
  so we don't spend requests on a model that just said "wait".
- Tested: `test_failures_are_not_retried_by_the_sdk` checks the fake server receives
  exactly one request.
- We give up the SDK's automatic retry for brief blips (e.g. one dropped connection).
  The next model in the fallback chain covers that instead. If single-provider retries
  become necessary, add them in the FallbackManager, not in the SDK.

## Alternatives considered
- **Keep SDK retries:** simplest, but hides 429s and slows fallback.
- **Retries in each adapter:** duplicates the logic per provider and still splits decisions
  between two layers.
