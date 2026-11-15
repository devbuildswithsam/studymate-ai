# ADR-0004: Fallback is filtered by capability; config errors still fall back

- **Status:** Accepted
- **Date:** 2026-11-15
- **Tickets:** SMA-22 (guide §7.5)

## Context
Free tiers fail often (429 rate limits, 503 overload), so the app needs a backup model.
But not every model can do everything: some can't call tools (needed for MCP in Stage 3)
or reliably return JSON (needed for quizzes). Falling back to such a model would give a
broken answer instead of an error. We also had to decide what to do when a model fails
because of *our* config (bad key, retired model id → 401/403/404).

## Decision
`FallbackManager.chat(messages, options, model_id, needs)`:
1. Builds a candidate list: the chosen model first (or, if none is chosen, the best enabled
   model), then the other enabled models by `priority`.
2. **Removes every model that lacks a needed capability** (`needs=["tools"]`,
   `["json"]`), even as a last resort. Choosing a model that lacks a needed capability, or
   a disabled one, is an immediate `LLMConfigError`.
3. Tries each candidate once; skips models still in their 429 cool-down.
4. Labels the answer: `ChatResult` has `requested_model`, `fallback_used` and a short,
   user-safe `fallback_reason` (e.g. `gemini-3.5-flash: rate-limited`).
5. If all fail, raises `AllModelsFailedError` with every reason.

**Config errors (401/403/404) also fall back**, so the user still gets an answer, but they
are logged at **error** level because, unlike a 429, they won't fix themselves.

## Consequences
- A tools or JSON request either gets a capable model or fails clearly: never a silently
  broken answer. Guarded by `test_tools_request_skips_models_without_tool_support` and
  `test_tools_request_fails_rather_than_use_a_model_without_tools` (checked by breaking the
  rule on purpose and seeing both fail).
- The UI can be honest about which model answered and why.
- A config mistake can hide behind a working fallback; we must watch the error log
  (later: the `llm_calls` monitoring table described in the project guide).
- Rate-limit memory lives in the process and resets on restart: fine for v1.0
  (local, single user); revisit if we run several workers.

## Alternatives considered
- **Fall back to any enabled model:** simpler, but a quiz could get non-JSON output and a
  tool request could be answered without the tool.
- **Stop on config errors:** clearer for the developer, worse for the user, who would get
  an error even though another model could answer.
