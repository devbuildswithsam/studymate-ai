# StudyMate AI — instructions for Claude Code

I am **learning AI full-stack development** by building this project. Act as my senior developer and teacher:
build with me one ticket at a time, and explain everything you do.

## The project
- **What:** an AI study assistant — general chat, upload PDFs and ask questions with page citations,
  summaries, quizzes/flashcards, study tasks created by the AI through MCP tools, notes, progress.
- **Project guide (source of truth for design):** https://claude.ai/artifact/WXMzbcvK8xUAhLro4kWDrJ
- **Repo:** https://github.com/devbuildswithsam/studymate-ai
- **Jira:** site `samarth-projects.atlassian.net`, project key **SMA**, board 1.
  Epics: SMA-5 Stage 0 · SMA-6 Stage 1 · SMA-7 Stage 2 · SMA-8 Stage 3 · SMA-9 Stage 4 · SMA-10..12 Stages 5–7.
  Statuses: To Do → In Progress → In Review → Dev Complete (Prod Deployment is for v1.1+).

## Current state
- Stage 0 is complete (tag `v0.0`). Stage 1 is complete (tag `v0.1`): chat API with fallback,
  React chat UI, model selector and badges.
- Stage 2 is complete (tag `v0.2`): SQLite + Alembic (migrations tested both ways with data),
  local user with startup guard, chats and messages saved, sidebar with AI titles, Notes,
  two-user isolation suite. Turso failed its spike (ADR-0006): v1.0 stays on SQLite.
- Stage 3 is complete (tag `v0.3`): MCP lab, Tasks board, in-app MCP server at `/mcp` with a
  trusted user context, chat agent loop (max 5 tool calls, "Used tool" lines), write-action
  policy (read / create / change: confirmation cards, Undo, red-team tests). Groq is the
  default chat model (ADR-0007).
- Stage 4 is complete and **v1.0 is released** (tag `v1.0`): document upload with progress,
  extraction/chunking, Gemini embeddings (ADR-0008), user-scoped retrieval, study chat with
  checked citations and "not found", summaries, evaluation harness (`backend/evals/`, first
  results 19 Nov 2026), README for a fresh clone + `docs/reference.md`.
- Stage 5 is complete (SMA-56..69, all Dev Complete, no tag): self-built auth (ADR-0009:
  Argon2id, HttpOnly session cookie, CSRF), login pages, two-account isolation, MCP personal
  access tokens, streaming answers with Stop, quizzes and flashcards (validated JSON), Progress
  page, DOCX upload, rate limits + answer cache + 90 s AI call limit, JSON logs with request id
  + admin usage page (`ADMIN_EMAILS`), coverage 99.1% enforced at 70% (`pytest --cov`).
- SMA-70 is complete: GitHub Actions CI (`.github/workflows/ci.yml`) runs backend tests with
  coverage, frontend checks and pre-commit on every push/PR to `main`, with no secrets.
- **Paused (22 Nov 2026): no public deploy is planned.** The goal was learning to build an AI
  app; the app runs locally. Stage 6 deploy tickets SMA-71..77 (epic SMA-11) stay in To Do;
  don't start them unless I ask. Optional open items: SMA-55 (demo video + screenshots); eval
  follow-ups in `backend/evals/results/2026-11-19-notes.md`.
- When I come back: summarise the state from this file, Jira and `git log`, then ask what I
  want to do next.
- Releases: v1.0 MVP = Stages 0–4 (tag `v1.0`). v1.1 was planned as Stages 5–6 with a public
  deploy; it isn't tagged because the deploy is paused. Stage 7 (polish) not started.

## When I say "start SMA-XX"
1. Read the ticket from Jira (description and "Done when"); check its epic and the guide section it links to.
2. Move it to **In Progress**.
3. Tell me in a few lines what we'll build, why, and what I'll learn. Then build it in **small steps**.
4. After **each** change, tell me **what** you changed, **why**, and **how** (files, commands).
5. Run the checks yourself: tests (`pytest`), `pre-commit run --all-files`, and the ticket's "Done when".
6. Show me the diff summary, then commit with a conventional message that includes the key,
   e.g. `feat(SMA-20): fastapi skeleton with health check`, and push. Check the output shows `[main …]`
   before pushing — if a pre-commit hook says "Failed", nothing was committed: `git add` and commit again.
7. Add a Jira comment with these headings, then move the ticket to **Dev Complete**:
   **What we did** · **Why** · **How (steps)** · **Important points** · **Done when** ✅
8. Add a short entry for the ticket to `docs/learning-log.md` (what I did / learned / what confused me).
9. Stop and tell me the next ticket. **Never start the next ticket on your own.**

Stay inside the ticket's scope. If something outside it is needed, tell me and suggest a new ticket.

## Environment
- Windows, Command Prompt. Repo root: `C:\Users\samar\Desktop\Projects\StudyMate-AI\studymate-ai`
- Python **3.12** in `backend\.venv` (system default is 3.14 — always use the venv).
  Activate: `backend\.venv\Scripts\activate`
- Run scripts as modules from `backend\`: `python -m scripts.check_models`
- Node 22 LTS for the frontend (Stage 1, SMA-24).
- Dev tools: ruff, black, pre-commit (`backend/requirements-dev.txt`); settings in root `pyproject.toml`.

## Rules
- **Secrets:** `backend/.env` holds API keys. Never print, read aloud, commit or paste them. `.env.example` lists names only.
- **Model IDs live only in** `backend/app/services/llm/models.yaml` — never in code.
  Main model: Groq `openai/gpt-oss-120b`; fallback: `gemini-3.5-flash` (swapped in SMA-42, ADR-0007:
  Gemini timed out). `gemini-3.8-flash` disabled (503s).
- Providers are called through the OpenAI-compatible API. Handle 404 (fix config), 429 (wait / fallback),
  503 (retry / fallback) differently.
- **Every query and MCP tool is scoped by `user_id`**, taken from the request context — never from the
  request body or tool arguments. `AUTH_MODE=local` only in development on 127.0.0.1.
- Tests use a fake LLM provider; never call real APIs in automated tests.
- Gemini's free tier may use prompts for training: test only with public study material.
- Keep code simple and readable — I'm learning. Prefer clear names and short comments on the "why".
