# ADR-0008: Embeddings use gemini-embedding-2 at 768 dimensions, with no fallback

- **Status:** Accepted
- **Date:** 2026-11-19
- **Tickets:** SMA-46

## Context
Stage 4 needs one vector per chunk so search (SMA-48) can compare a question with the
document. The guide asks for an `EmbeddingProvider` separate from the chat providers and
for Gemini's embedding API (no local models). On 19 Nov 2026 Gemini's OpenAI-compatible
endpoint listed `gemini-embedding-001`, `gemini-embedding-2` and `gemini-embedding-2-preview`.
Probed with public textbook sentences:

| Model | Default size | At `dimensions=768` | Vector length (norm) at 768 |
|---|---|---|---|
| gemini-embedding-2 | 3072 | works | 1.000 (normalised) |
| gemini-embedding-001 | 3072 | works | 0.581 (not normalised) |

Also seen: at most **100 texts per request** (101 gives HTTP 400); the free tier answered
**429** after a handful of calls; and Gemini leaves out `"index": 0` in the reply (Google's
APIs omit fields equal to their default). Two sentences about energy conservation scored
0.831; an unrelated biology sentence 0.656.

## Decision
- `models.yaml` gets an `embeddings:` section: `gemini-embedding-2`, `dimensions: 768`,
  `version: 1`, `batch_size: 50`. The registry validates it (batch size at most 100).
- Vectors are stored as float32 BLOBs (768 × 4 = 3 KB per chunk); the database rejects a
  vector whose length doesn't match `embedding_dim` (SMA-44).
- **No fallback model for embeddings.** Vectors from two models (or two sizes) can't be
  compared, so a failure marks the document `failed` and it can be retried. Finished
  batches are kept, so a retry continues where it stopped.
- A document never mixes models: vectors from another model, version or size are cleared
  and redone. Changing the model or size means bumping `version` in `models.yaml`.

## Consequences
- Normalised vectors make cosine similarity a plain dot product (SMA-48).
- 768 instead of 3072 numbers: a quarter of the storage and faster search, at a small
  cost in accuracy (the evaluation in SMA-51 will tell us if that matters).
- Rate limits will show up as failed documents with a "try again in a minute" message,
  not as hidden waits.
- Every chunk of every document must be re-embedded if the model changes (bump
  `version`); the stored model and version make that safe.

## Alternatives considered
- **gemini-embedding-001 at 768:** works, but its vectors aren't normalised at that size,
  so every comparison would need extra maths.
- **Full 3072 dimensions:** 12 KB per chunk and 4× slower search, for a gain we haven't
  measured yet.
- **Fall back to another embedding provider:** would mix incomparable vectors; rejected by
  the guide (7.5).
