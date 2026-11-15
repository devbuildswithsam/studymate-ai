# ADR-0001: Model ids live only in `models.yaml`

- **Status:** Accepted
- **Date:** 2026-11-13
- **Tickets:** SMA-16, SMA-17, SMA-22

## Context
We use free LLM tiers, and their model lists change often. In SMA-16, `gemini-2.5-flash`
returned HTTP 404 ("no longer available to new users") and `gemini-3.8-flash` returned
HTTP 503 (overloaded). If model names were spread through the code, every change would mean
hunting through files and redeploying code, not just config.

## Decision
Every model id lives in one file: `backend/app/services/llm/models.yaml`. Code never contains
a model id. Each entry also records what we know about the model: provider, display name,
priority (fallback order), context window, `supports_tools`, `supports_json`, `default_for`
and `enabled`.

Since SMA-22 the file is validated with Pydantic when the app starts (`registry.py`):
unknown fields (typos), unknown providers, duplicate ids, shared priorities and "no model
enabled" stop the app with a clear message.

## Consequences
- Switching, adding or disabling a model is a one-line config change
  (e.g. `gemini-3.8-flash` is kept with `enabled: false` until it stops returning 503).
- Capabilities are recorded after testing them (`python -m scripts.check_models`);
  `null` means "not tested yet" and is treated as **no**.
- A broken `models.yaml` prevents startup. That is intended: better to fail at once than on
  a user's first message.
- Rule for reviews: a model id in Python code is a bug.

## Alternatives considered
- **Model names in `.env`** (what SMA-16 did first): fine for one model, but can't hold
  capabilities, priorities or several models per provider.
- **Hard-coded constants:** simplest, but every model change becomes a code change.
