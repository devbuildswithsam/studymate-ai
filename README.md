# StudyMate AI

An AI study assistant: chat, ask questions about your PDFs with page citations,
summaries, quizzes, and study tasks created by the AI through MCP tools.

> Status: v1.0 MVP in progress (Stage 0 — setup). Built in public.

## Tech stack
React + TypeScript · FastAPI · SQLite + SQLAlchemy · MCP (Python SDK) · Gemini / Groq (free tiers)

## Project structure
- `backend/` — FastAPI API, LLM providers, RAG, MCP server
- `frontend/` — React app
- `docs/` — learning log and architecture decision records (ADRs)

## Local setup
_Coming in Stage 1._

## Roadmap
- v1.0 — local MVP: chat, document Q&A with citations, notes, AI tasks
- v1.1 — auth, streaming, quizzes, public deployment
- v1.2 — polish and showcase