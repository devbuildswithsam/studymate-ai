# StudyMate AI

An AI study assistant: chat, ask questions about your PDFs with page citations,
summaries, quizzes, and study tasks created by the AI through MCP tools.

> **Status:** v1.0 MVP in progress — Stage 2 (database). Built in public.
> Done so far: backend skeleton (config, health check, CORS, one error format), the LLM
> provider layer (Gemini + Groq adapters, model registry, automatic fallback),
> `GET /api/models`, `POST /api/chat` (in-memory history), the frontend shell and the
> **chat page** (Markdown + maths answers, copy button, friendly error toasts, model
> selector with a "Use fallback" toggle, and badges showing which model answered).
> v1.0 is **local and single-user only**: don't deploy it publicly before auth (v1.1).

## Tech stack
React + TypeScript · FastAPI · SQLite + SQLAlchemy · MCP (Python SDK) · Gemini / Groq (free tiers)

## Prerequisites
- **Python 3.12** (check with `py -3.12 --version` on Windows, `python3.12 --version` elsewhere)
- **Git**
- **Node 22 LTS** and npm — for the frontend
- Free API keys (optional to start; tests don't need them):
  - Gemini: [Google AI Studio](https://aistudio.google.com/apikey)
  - Groq: [Groq console](https://console.groq.com/keys)

> Gemini's free tier may use prompts for training. Only send public study material.

## Local setup
Commands are for **Windows Command Prompt**, run from the repo root unless stated.
On macOS/Linux use `python3.12` instead of `py -3.12`, `source .venv/bin/activate` to
activate, and `cp` instead of `copy`.

```bat
git clone https://github.com/devbuildswithsam/studymate-ai.git
cd studymate-ai\backend

:: 1. Virtual environment with Python 3.12
py -3.12 -m venv .venv
.venv\Scripts\activate

:: 2. Packages: the app, then the dev tools (pytest, ruff, black, pre-commit)
python -m pip install -r requirements.txt -r requirements-dev.txt

:: 3. Settings: copy the example, then put your API keys in .env
copy .env.example .env

:: 4. Database: create/upgrade backend\app.db (SQLite) to the latest migration
alembic upgrade head

:: 5. Create the local user (local@studymate.dev). Safe to run again
python -m scripts.seed
```

`backend\.env` holds your secrets. It is git-ignored — **never commit it or paste it anywhere**.
`.env.example` only lists the setting names:

| Setting | Default | Meaning |
|---|---|---|
| `ENV` | `development` | `development`, `test` or `production` |
| `AUTH_MODE` | `local` | `local` = single user, no login, only requests from this computer. Refused when `ENV=production` |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | The only origin allowed by CORS |
| `DATABASE_URL` | `sqlite:///./app.db` | The database. `./` = the folder you start from, so run the API and `alembic` from `backend\` |
| `GEMINI_API_KEY`, `GROQ_API_KEY` | empty | Provider keys. A model without a key shows as `no_key` |

Finally, turn on the commit hooks (from the repo root, venv active):

```bat
cd ..
pre-commit install
```

### Frontend
```bat
cd frontend
npm install
```

## Run the API
From `backend\` with the venv active:

```bat
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- Interactive API docs: <http://127.0.0.1:8000/docs>
- `GET /api/health` — status, version, env and auth mode
- `GET /api/models` — enabled models and their status (`available`, `rate_limited`, `no_key`)
- `POST /api/chat` — send `{"message": "..."}` (plus `conversation_id` to continue a
  conversation, optionally `model` and `allow_fallback`, default `true`). Returns the reply, which model answered, whether a
  fallback was used, and token counts. History is in memory: a restart forgets it.

Keep `--host 127.0.0.1` (local only): `AUTH_MODE=local` treats every request as the local
user, so it answers **403** to requests from other machines, and the app refuses to start with
`ENV=production`. If chat says "The local user is missing", run `python -m scripts.seed`.
`--reload` restarts the server when you save a file.

If `backend/app/services/llm/models.yaml` has a mistake, the server refuses to start and
names the field (see [ADR-0001](docs/adr/0001-model-ids-only-in-models-yaml.md)).

## Run the frontend
In a second terminal (keep the API running):

```bat
cd frontend
npm run dev
```

Open <http://localhost:5173> and chat on the **Chat** page (Enter sends, Shift+Enter adds a
new line). The sidebar shows **API online** when the backend answers; if it's stopped, sending
shows a "Can't reach the server" toast. Chats are kept in memory: restarting the API forgets them.
React always calls relative paths like `/api/health`; Vite's dev proxy forwards `/api` to
`http://127.0.0.1:8000`, so there's no CORS setup and no backend URL in the frontend code.

## Database migrations
The schema is changed only through **Alembic migrations** (`backend\alembic\versions\`), never
`create_all()`, so an existing database can be upgraded without losing data.
From `backend\` with the venv active:

```bat
alembic upgrade head                                  :: apply all migrations (safe to repeat)
alembic current                                       :: which migration the database is at
alembic revision --autogenerate -m "add notes table"  :: draft a migration from model changes; always read it
```

`app.db` is git-ignored. Tests never touch it: each one uses a temporary SQLite file.

## Tests and code quality
Tests never call real AI APIs: they use a fake provider and a fake HTTP server.

```bat
:: from backend\ (or the repo root) with the venv active
pytest

:: all hooks on all files: ruff (lint + import order), black (format), whitespace, YAML, secrets
pre-commit run --all-files
```

Frontend (from `frontend\`):

```bat
npm test               :: Vitest + Testing Library (fetch is faked: no backend needed)
npm run lint           :: ESLint
npm run format:check   :: Prettier (npm run format to fix)
npm run build          :: type-check + production build
```

The hooks also run on every `git commit`. If one prints **Failed — files were modified**, the
commit did **not** happen: run `git add` and commit again.

Commit messages follow conventional commits with the Jira key, e.g.
`feat(SMA-22): validated model registry, fallback manager and models endpoint`.

## Dev scripts
From `backend\` with the venv active. These **do** call the real APIs (they need keys):

```bat
:: ask one question to a provider
python -m scripts.hello_llm gemini
python -m scripts.hello_llm groq --temperature 1
python -m scripts.hello_llm groq --list-models

:: check each enabled model for chat, tool calling and JSON output
python -m scripts.check_models
```

## Project structure
```text
backend/
  app/
    main.py            FastAPI app: CORS, error handlers, routers
    config.py          settings from backend/.env (pydantic-settings)
    db/                SQLAlchemy: base.py (models' base class), session.py (engine, get_db),
                       seed.py (the local user)
    models/            tables: users, conversations + messages, notes, llm_calls
    errors.py          one error format: {"error": {"code", "message"}}
    api/               routers: health.py, models.py, chat.py
                       (+ deps.py: get_current_user, the only source of user_id)
    services/llm/      models.yaml (model registry), LLMProvider + adapters,
                       factory, FallbackManager, FakeProvider
    services/chat_history.py  in-memory conversations, per user
  alembic/             database migrations (env.py wired to the app's settings and models)
  scripts/             seed.py (local user) and dev scripts that call real APIs
  tests/               pytest tests (no real API calls)
frontend/
  src/
    App.tsx            routes: every page renders inside the AppShell
    api/               client.ts (fetch + our error format), one file per endpoint
    components/        chat/ (MessageList, Markdown, ChatInput, CopyButton), layout/,
                       HealthStatus, ui/ (shadcn/ui, generated)
    lib/               errors.ts (friendly error messages), utils.ts
    pages/             one component per page (ChatPage; the rest are placeholders)
    test/              Vitest setup and render helpers
  vite.config.ts       plugins, @ alias, /api dev proxy, Vitest settings
docs/
  adr/                 architecture decision records: why things are the way they are
  learning-log.md      what I did and learned, per ticket
experiments/           throwaway proofs of concept (e.g. Vercel streaming PoC)
pyproject.toml         ruff, black and pytest settings
```

## Documentation
- [Architecture decision records](docs/adr/README.md) — the reasons behind key design choices
- [Learning log](docs/learning-log.md) — one entry per ticket
- Work is tracked in Jira (project **SMA**); each ticket has a comment with what/why/how

## Roadmap
- v1.0 — local MVP: chat, document Q&A with citations, notes, AI tasks
- v1.1 — auth, streaming, quizzes, public deployment
- v1.2 — polish and showcase
