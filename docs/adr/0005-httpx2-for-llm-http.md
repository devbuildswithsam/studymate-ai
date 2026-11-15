# ADR-0005: Use (and mock) `httpx2`, the HTTP client of the `openai` SDK

- **Status:** Accepted
- **Date:** 2026-11-15
- **Tickets:** SMA-20, SMA-21

## Context
The `openai` SDK (3.50) sends its requests with **`httpx2`**, and its `http_client`
argument expects an `httpx2.Client`. FastAPI's `TestClient` needs the separate **`httpx`**
package. Both ended up in the venv, which is confusing. To test the adapters without real
API calls (CLAUDE.md rule) we need to replace the network with a fake server, and that fake
must be the kind of client the SDK actually uses.

## Decision
- The LLM adapters accept an optional `http_client: httpx2.Client` and pass it to the SDK.
- Adapter tests use `httpx2.MockTransport(handler)`: the handler plays the provider's server,
  returns the response we choose (200, 429, 503, a timeout…), and records what we sent.
- `httpx2` is pinned in `backend/requirements.txt` because our code imports it directly.
- `httpx` stays in `backend/requirements-dev.txt`, only for FastAPI's `TestClient`.

## Consequences
- Adapter tests are fast, free, repeatable and check both directions: the request we sent
  (model, messages, key, JSON mode) and how we read the reply or error.
- Two similar HTTP packages in the project: `httpx2` for LLM calls, `httpx` for API tests.
  Don't mix them up: an `httpx.MockTransport` will not work with the `openai` SDK.
- If a future `openai` release changes its HTTP client, the adapter tests will break first;
  update this ADR then.

## Alternatives considered
- **Patch the SDK's methods with `unittest.mock`:** skips the SDK's real request building
  and error parsing, so the tests would prove less.
- **A third-party HTTP-mocking library:** most target `httpx`/`requests`, not `httpx2`, and
  `MockTransport` already does what we need.
