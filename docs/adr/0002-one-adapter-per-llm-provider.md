# ADR-0002: One adapter per LLM provider behind `LLMProvider`

- **Status:** Accepted
- **Date:** 2026-11-15
- **Tickets:** SMA-21 (guide §7.5)

## Context
Gemini and Groq both offer an OpenAI-compatible Chat Completions API, so one client could
talk to both by changing `base_url`, `api_key` and `model`. But "compatible" is a starting
point, not a guarantee: providers differ in error formats, tool calling, JSON output and
streaming, and Gemini's compatibility layer has documented gaps. Chat, summaries and quizzes
should not each need to know these differences.

## Decision
All code talks to one interface, `LLMProvider` (`app/services/llm/base.py`):
`chat(messages, options) -> ChatResponse` and `supports(capability)`.

- `ChatResponse` has the same fields whatever the provider: text, tokens_in, tokens_out,
  model, provider, latency_ms.
- Shared OpenAI-compatible code lives in `OpenAICompatibleProvider` (`openai_compat.py`).
- Each provider gets its own subclass (`GeminiProvider`, `GroqProvider`) that overrides only
  what differs. Example: on HTTP 429 Gemini puts the wait time in the body (`retryDelay`)
  instead of the `Retry-After` header. (This follows Google's usual error format; we have
  not yet seen a real Gemini 429 in this project, so check it the first time one happens.)
- Each adapter turns provider errors into our own types (`exceptions.py`):
  429 → `RateLimitedError`, 5xx / no connection → `ProviderUnavailableError`,
  timeout → `ProviderTimeoutError`, 401/403/404 → `LLMConfigError`.
- `FakeProvider` implements the same interface for tests, so tests never call real APIs.

## Consequences
- Adding a provider (e.g. OpenRouter) = one new adapter class plus a line in
  `factory.py` and `models.yaml`; calling code doesn't change.
- Provider quirks have one obvious home (e.g. Gemini tool-calling fixes in Stage 3).
- The rest of the app handles errors by *what happened*, not by provider.
- More classes than "one client for everything", and `GroqProvider` is almost empty for now.
  That is accepted: it reserves a place for Groq-specific fixes.

## Alternatives considered
- **One shared OpenAI client with `if provider == ...` branches:** less code at first, but
  quirks pile up in one place and every change risks breaking the other provider.
- **A third-party multi-provider library:** hides the details we're here to learn, and adds
  a dependency whose behaviour (retries, error mapping) we wouldn't control.
