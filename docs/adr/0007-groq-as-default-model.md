# ADR-0007: Groq GPT-OSS 120B is the default chat model; Gemini becomes the fallback

- **Status:** Accepted
- **Date:** 2026-11-18
- **Tickets:** SMA-42 (decided by the project owner)

## Context
Until now `gemini-3.5-flash` was the default for chat, study and quiz, and Groq's
`openai/gpt-oss-120b` the fallback. SMA-42 sends MCP tools with chat messages, so each
message can take several model calls. Measured on 18 Nov 2026 (free tiers, from India):

| Call | Gemini 3.5 Flash | GPT-OSS 120B (Groq) |
|---|---|---|
| One-sentence question, no tools | timed out after 30 s (twice) | 0.6 to 0.8 s |
| Tool call (SMA-39 / SMA-42 probes) | 75 to 90 s, `reasoning_effort=low` no faster; `none` timed out | about 1 s |

On 16 Nov the same plain Gemini call took about 2.5 s, so this looks like a slow free tier
rather than tools. With Gemini first, every slow call waits for the 60 s timeout before
falling back.

## Decision
- `openai/gpt-oss-120b` gets `default_for: [chat, study, quiz]` and priority 1.
- `gemini-3.5-flash` stays enabled with priority 2: the first fallback, and selectable in
  the model menu.
- Only `models.yaml` changes (ADR-0001: model ids live only there). A test checks that the
  chat default supports tools and is first in the fallback order.

## Consequences
- Chat and tool use answer in about a second while Groq is healthy.
- Gemini's free tier may use prompts for training; with Groq as default, fewer prompts go
  there (CLAUDE.md still says: test only with public study material).
- Groq's free tier has its own rate limits; a 429 falls back to Gemini (SMA-22).
- If Gemini becomes fast again, swapping back is a two-line change in `models.yaml`;
  write a new ADR that replaces this one.

## Alternatives considered
- **Groq only for tool turns** (a new `default_for: tools`): two defaults to explain, and
  normal chat would still wait for Gemini.
- **Keep Gemini first and rely on fallback:** works, but about a minute of waiting for
  every slow Gemini step.
