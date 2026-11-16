# Learning log

A short entry per ticket: what I did, what I learned, and what confused me.

---

## SMA-13 — Toolchain and virtual environment
**Date:** 13 Nov 2026

**What I did**
- Installed Python 3.12.10 alongside my existing Python 3.14 (picked with `py -3.12`), Node v22.23.5 LTS and Git 2.56.0.
- Created `backend\.venv` with `py -3.12 -m venv .venv` and activated it with `.venv\Scripts\activate`.
- Renamed the folder `StudyMate AI` → `StudyMate-AI` and recreated the venv.

**What I learned**
- A virtual environment gives the project its own Python and packages, so nothing clashes with other projects.
- Inside the venv, `python` means 3.12 even though 3.14 is my system default.
- A venv stores its own path, so renaming the folder breaks it; delete and recreate it.
- Spaces in folder paths can break Python and Node tools.

**What confused me**
- …

---

## SMA-14 — GitHub repo and project structure
**Date:** 13 Nov 2026

**What I did**
- Set my Git name, email and `main` as the default branch.
- Found my Desktop folder was already a Git repo (an old `git init`); ran `git init` inside `studymate-ai` so the project has its own repo.
- Created `backend/`, `frontend/`, `docs/adr/`, `.github/workflows/` with placeholder files.
- Added `.gitignore`, `backend/.env.example`, `README.md` and this log.
- First commit, then pushed to https://github.com/devbuildswithsam/studymate-ai

**What I learned**
- `git rev-parse --show-toplevel` shows which repo a folder belongs to.
- Git doesn't track empty folders, hence `.gitkeep` / `__init__.py`.
- `git status` shows a new folder as one entry until its files are added.
- Add `.gitignore` before the first commit so secrets (`.env`) and `.venv` can never be committed.
- GitHub error GH007 blocked my push because it would expose my private email. Fixed by using the GitHub noreply address and `git commit --amend --reset-author --no-edit`.
- Check a push with `git status` → "up to date with 'origin/main'".

**What confused me**
- …

---

## SMA-15 — Free API keys
**Date:** 13 Nov 2026

**What I did**
- Created a Gemini API key (Google AI Studio) and a Groq API key (Groq console).
- Stored both only in `backend/.env`; confirmed with `git check-ignore -v backend\.env` that Git ignores it.

**Free-tier limits I saw** (they change; check the consoles again later)
- Gemini (AI Studio): …
- Groq (Settings → Limits): …

**What I learned**
- An API key is a password: never in code, commits, chats or screenshots. If one leaks, delete it in the console and create a new one.
- Gemini's free tier may use prompts to improve Google products → test only with public study material.
- Groq says it doesn't train on API data.

---

## SMA-16 — First LLM calls (Gemini + Groq)
**Date:** 13 Nov 2026

**What I did**
- Installed `openai` and `python-dotenv` (pinned in `requirements.txt`).
- Wrote `backend/scripts/hello_llm.py`: one OpenAI-compatible client; only `base_url`, API key and model change per provider.
- Model names live in `.env` (`GEMINI_MODEL`, `GROQ_MODEL`), not in code.

**Results**
- Groq `openai/gpt-oss-120b`: answered in ~2.2 s, 102 tokens in / 104 out.
- Gemini `gemini-2.5-flash`: HTTP 404, "no longer available to new users".
- Gemini `gemini-3.8-flash`: HTTP 503, "high demand", then …
- Temperature 0 vs 1: …
- Gemini vs Groq speed: …

**What I learned**
- The `messages` list (system + user) is the whole conversation the model sees.
- Show the provider's real error (`e.body`): it told me exactly which model to use.
- `--list-models` shows what exists, not what my free key is allowed to use.
- Error codes need different handling:
  - 404 → wrong or retired model: fix config, don't retry
  - 429 → rate limit hit: wait or use the fallback provider
  - 503 → provider overloaded: retry later or use the fallback
- This is why the app needs a fallback provider and model names in config.

**What confused me**
- …

---

## SMA-20 — FastAPI skeleton: config, health check, CORS, pytest
**Date:** 14 Nov 2026

**What I did**
- Built the backend base: `app/config.py` (settings from `.env`), `app/errors.py` (one error shape), `app/api/health.py` (`GET /api/health`) and `app/main.py` (app + CORS).
- Wrote the first tests (`tests/conftest.py`, `tests/test_health.py`): 4 pass.
- Ran `uvicorn app.main:app` and opened `/docs` (Swagger UI) and `/api/health`.

**What I learned**
- **ASGI:** uvicorn is the server, `app` is the application it calls for every request.
- **pydantic-settings** checks `.env` at startup; `SecretStr` keeps keys from showing up in prints and logs.
- **Routers** keep each feature in its own file; `main.py` just includes them.
- **Dependency injection:** `Annotated[Settings, Depends(get_settings)]` lets a route ask for settings, and tests swap them with `app.dependency_overrides`.
- **CORS** is enforced by the browser: the API names the one origin (`http://localhost:5173`) allowed to read its responses.
- Exception handlers turn every error into `{"error": {"code", "message"}}`, and a 500 never shows internals.
- ruff B008 flags `= Depends(...)` defaults; `Annotated` is the modern fix. Ruff's `src` setting tells it which imports are ours.

**What confused me**
- …

---

## SMA-21 — LLMProvider interface with Gemini and Groq adapters
**Date:** 15 Nov 2026

**What I did**
- Built `app/services/llm/`: `exceptions.py` (typed errors), `base.py` (the `LLMProvider` interface), `openai_compat.py` (shared adapter), `gemini.py`, `groq.py` and `fake.py`.
- Wrote 39 tests that fake the provider's server with `httpx2.MockTransport`: no real API calls.

**What I learned**
- **Interface (abstract base class):** `LLMProvider` declares `chat()`; Python refuses to create a provider that forgets it.
- **Adapter pattern:** shared code in one parent class; each provider overrides only what differs (Gemini reads its 429 wait time from the body).
- **Typed errors** say *what happened*, not who said it: 429 → `RateLimitedError`, 5xx → `ProviderUnavailableError`, 401/403/404 → `LLMConfigError` (fix config, don't retry).
- **Mocking HTTP:** pass a fake `http_client` to the `openai` SDK and check both what we sent and what we got back.
- `@pytest.mark.parametrize` runs one test for many inputs (Gemini and Groq, each status code).
- `max_retries=0`: the SDK retries silently by default; retry/fallback belongs in one place (SMA-22).
- Catch a subclass exception (`APITimeoutError`) before its parent (`APIConnectionError`).

**What confused me**
- …

---

## SMA-22 — Model registry loader, FallbackManager and GET /api/models
**Date:** 15 Nov 2026

**What I did**
- Validated `models.yaml` with Pydantic (`registry.py`); the app now refuses to start if it's wrong.
- Added `factory.py` (model → ready adapter), `fallback.py` (`FallbackManager`) and `GET /api/models`.
- 30 new tests using `FakeProvider`s and a `FakeClock`; 73 in total.

**What I learned**
- `extra="forbid"` turns a typo like `priorty:` into a clear error instead of a silently ignored field.
- A `model_validator` checks rules across fields (unknown provider, duplicate ids, shared priorities).
- **Factory pattern:** say *which model*, get a ready object without knowing its class, key or URL.
- **Fallback by capability:** a tools request only falls back to models with `supports_tools: true`; failing is better than a broken answer.
- Every answer carries a label (`fallback_used`, `fallback_reason`) so the UI can be honest about it.
- Remembering 429s with a cool-down; injecting the clock makes "60 seconds later" instant in tests.
- **Mutation check:** break the code on purpose and confirm the test fails, so the test really guards the rule.

**What confused me**
- …

---

## SMA-53 — ADRs for early decisions and README setup instructions
**Date:** 15 Nov 2026

**What I did**
- Started `docs/adr/` with an index, a template and five ADRs (model registry, adapters, no SDK retries, capability-aware fallback, `httpx2`).
- Rewrote the README: status, setup, `.env` settings, running the API, tests, hooks, scripts, project structure.
- Tested the README by following it on a fresh clone from GitHub: tests passed and the server ran, with no API keys.

**What I learned**
- An **ADR** records one decision: Context → Decision → Consequences (+ alternatives). Code shows *what*; ADRs keep *why*.
- ADRs are never rewritten; a changed decision gets a new ADR that supersedes the old one.
- Setup docs must be tested like code: follow them on a clean machine/clone, exactly as written.
- Docs should only state what's verified (we marked the Gemini `retryDelay` quirk as "not yet seen live").

**What confused me**
- …

---

## SMA-23 — POST /api/chat with in-memory conversation history
**Date:** 15 Nov 2026

**What I did**
- Built `POST /api/chat` **test-first**: 5 red → green rounds and one refactor.
- Added `ConversationStore` (memory per user), `get_current_user_id()` ("local" for now) and the chat limits.
- Filled the SMA-22 gap with factory tests.
- First real conversation through the whole app: Gemini remembered turn 1 when answering turn 2.

**What I learned**
- **Test-first:** write the test, watch it fail for the *right* reason (404, missing module, wrong behaviour), then write only enough code to pass. A test that already passes is fine when it guards a boundary (exactly 4000 chars).
- The model has **no memory**: every call re-sends the conversation (`tokens_in` went 43 → 84 on turn 2).
- **Context window / trimming:** send only the last 10 messages; the store keeps everything.
- `StringConstraints` rejects bad input (too long, empty) with 422 before my code runs.
- Scope by `user_id` from the request context; another user's conversation looks exactly like a missing one (404).
- Save a turn only after the AI answers, so failures leave nothing half-done.
- **Tests can be wrong too:** a fake replaced after the manager cached it did nothing, and a helper turned `""` into `None`. Mutation checks and suspicious passes catch this.
- **Characterisation tests** pin down existing code before changing it.

**What confused me**
- …

---

## SMA-24 — Frontend setup: React + Vite + TypeScript + Tailwind + shadcn/ui
**Date:** 15 Nov 2026

**What I did**
- Created `frontend/` with Vite (React + TS), Tailwind v4, shadcn/ui, React Router, TanStack Query, ESLint + Prettier.
- Added Vitest + Testing Library so the frontend is test-first too: 16 tests.
- Built the app shell (sidebar + main) and `HealthStatus`, which reads `/api/health` through Vite's dev proxy.
- Ran FastAPI and Vite together and confirmed `/api` requests on port 5173 reach FastAPI.

**What I learned**
- **Dev proxy:** React calls relative `/api/...` paths; Vite forwards them to 127.0.0.1:8000. One origin = no CORS, no backend URL in the code.
- **shadcn/ui** copies component source into my repo (`src/components/ui/`) instead of installing a library.
- **TanStack Query** handles loading / error / caching for API calls (`useHealth()`).
- **Testing Library** queries by role (`navigation`, `link`, `main`, `status`) like a user or screen reader would; jsdom is a fake browser for tests.
- `NavLink` adds `aria-current="page"` itself; `end` stops `/` from matching every page.
- Fast refresh needs files that export only components.
- Check `--help` before running unfamiliar CLIs; check unexpected packages before trusting them (`cn` was legitimate).
- `npm audit --omit=dev` shows what ships to the browser; build-only tools belong in devDependencies.

**What confused me**
- …

---

## SMA-25 — General chat page: message list, input, loading, Markdown, errors
**Date:** 15 Nov 2026

**What I did**
- Built the chat page test-first: bubbles, input (Enter / Shift+Enter), thinking indicator, Markdown + maths answers, Copy button, friendly error toasts. 24 new frontend tests (40 total).
- Checked the real system: a Gemini answer through the Vite proxy, and what the proxy does when the backend is stopped.

**What I learned**
- **XSS:** AI output is untrusted. react-markdown escapes raw HTML by default; `skipHtml` drops it too; never add `rehype-raw`. The mutation check showed which change the test really guards.
- **Optimistic UI:** show the question at once; on error remove it, give the text back, show a toast.
- `useMutation` (send/change) vs `useQuery` (read).
- **Check reality, not assumptions:** a dead backend behind Vite's proxy gives an empty **HTTP 502**, not a failed fetch; my first error mapping was wrong.
- **Tests can leak:** Sonner keeps toasts in module memory, so a toast from one test made another pass falsely. Run suspicious passes alone; reset library state after each test.
- jsdom lacks some browser APIs (`matchMedia`): add small stand-ins in the test setup.
- `npm ls <pkg>` finds duplicate versions; npm `overrides` forces one version (KaTeX 0.16 → 0.19).

**What confused me**
- …

---

## SMA-26 — Model selector and response badges (model, General, fallback)
**Date:** 15 Nov 2026

**What I did**
- Backend: `allow_fallback` on `POST /api/chat` (test-first).
- Frontend: `ModelSelector` (model dropdown with status + "Use fallback" checkbox) and `MessageBadges` ("General AI", model name, ⚠ fallback with the reason), wired into the chat page. 16 new tests (101 backend, 52 frontend).
- Real check: switching between Gemini and Groq changes who answers; with a deliberately broken Gemini key (set only in that process's environment), Groq answered with the fallback label, and with fallback off the API returned 503.

**What I learned**
- A UI toggle can need a backend change first: the API always fell back until `allow_fallback` existed.
- Native `<select>` / checkbox are accessible by default and easy to test.
- Hover text (`title`) alone isn't accessible: add the same text as `aria-label`.
- Show the model that **actually** answered, not the one selected; a mutation check proved the test guards this.
- Derive values (`chosen ?? default`) instead of copying them into state with an effect.
- Environment variables override `.env` in pydantic-settings: a safe way to simulate a broken key without touching secrets.
- Real APIs surprise you: Gemini rejects a bad key with HTTP 400, not 401/403.
- `curl -s` treats a 502 as success; use `curl -f` when waiting for a server.

**What confused me**
- …

---

## SMA-54 — Map Gemini's HTTP 400 "invalid API key" to LLMConfigError
**Date:** 15 Nov 2026

**What I did**
- Follow-up from SMA-26: the Gemini adapter now treats a 400 that mentions the API key (or `API_KEY_INVALID`) as a configuration error; every other 400 stays an ordinary error.
- 4 new tests (105 backend). Live check with a deliberately wrong key: the reason now says "configuration error" and the log line is the loud error one.

**What I learned**
- Capture the real error before writing the test: Gemini's body was `"Please pass a valid API key"` with the generic `INVALID_ARGUMENT`, not the `API_KEY_INVALID` I had guessed in the ticket.
- Put provider quirks in that provider's adapter (override one method); the shared code and the FallbackManager didn't change.
- A "guard" test that already passes before the fix is useful: it stops the fix from becoming too broad (a mutation that made every 400 a config error was caught).
- When a test fails, check the test too: my expected fallback model was wrong, not the code.

**What confused me**
- …

---

## SMA-27 — SQLAlchemy 2.0 + Alembic setup with SQLite
**Date:** 16 Nov 2026

**What I did**
- Started Stage 2 (database). `app/db/`: the models' `Base`, an engine with SQLite foreign keys switched on, and the `get_db` dependency (one session per request).
- `alembic init`, wired to the app's `DATABASE_URL` and `Base.metadata`; `alembic upgrade head` creates `backend/app.db`.
- 5 tests, each on a temporary SQLite file (110 backend tests).

**What I learned**
- **Engine vs session:** the engine knows how to connect; a session is one unit of work. Nothing is saved until `commit()`, and closing without a commit throws the work away (a rollback).
- **Migrations instead of `create_all()`:** `create_all` only creates missing tables; it never changes existing ones. Migrations are small, versioned scripts that move a real database (with data) from one schema to the next.
- **SQLite ignores foreign keys** unless every connection runs `PRAGMA foreign_keys=ON`.
- SQLite can't `ALTER` most things, so Alembic's "batch mode" rebuilds the table, and constraints need predictable names.
- Mutation checks also find **unneeded** code: my explicit `rollback()` was redundant, so I removed it.
- Library setup can have side effects: Alembic's logging config silenced the app's loggers until I set `disable_existing_loggers=False`.

**What confused me**
- …

---

## SMA-28 — Models and first migration: users, conversations, messages, notes, llm_calls
**Date:** 16 Nov 2026

**What I did**
- Five SQLAlchemy models in `app/models/` and one Alembic migration that creates them (and drops them on downgrade).
- 17 tests on a temporary database built by the real migration (122 backend tests).
- Ran upgrade → downgrade → upgrade on my own `app.db`.

**What I learned**
- **Foreign keys + `ON DELETE`:** CASCADE deletes the children too (user → conversations → messages); SET NULL keeps the row and empties the link (a note survives when its chat message is deleted).
- **Indexes** on `user_id` / `conversation_id` make "this user's conversations" fast; the database doesn't add them for you.
- **CHECK constraints** let the database refuse bad values (`role = 'robot'`), even when the Python code has a bug.
- **Autogenerate writes a draft:** read every line. A test that compares the models with the migrated database catches "changed a model, forgot the migration".
- Testing with plain SQL (`DELETE FROM users`) proves the *database* cascades, not just the ORM.
- `TYPE_CHECKING` imports give type hints between models without circular imports.

**What confused me**
- …

---

## SMA-29 — Single-user local auth mode with startup guard
**Date:** 16 Nov 2026

**What I did**
- `python -m scripts.seed` creates the local user `local@studymate.dev` (safe to run again).
- `get_current_user()` returns that user from the database; chat now runs as the real user id.
- Guards: the app refuses to start with `ENV=production` + `AUTH_MODE=local`, and local mode answers 403 to other machines.
- 17 tests (139 backend tests), including one that fails if any endpoint accepts `user_id`.

**What I learned**
- **Identity comes from one dependency.** Routes ask `Depends(get_current_user)`; they never read a user id from the request. Real auth in v1.1 changes only this function.
- **Idempotent seed scripts:** "find, else create", so running twice can't make two users.
- **Error messages can leak secrets:** pydantic's settings error printed every input value, API keys included. `hide_input_in_errors=True` fixes it, and a test keeps it fixed.
- **Test the real startup:** a subprocess running `import app.main` proves the app exits, not just that a class raises.
- **Turn rules into tests:** scanning the OpenAPI spec for `user_id` makes the "never from the request" rule automatic.
- Mutation checks again: removing each guard made a test fail.

**What confused me**
- …

---

## SMA-30 — Repository layer, conversations CRUD, chat messages saved in the database
**Date:** 16 Nov 2026

**What I did**
- `app/repositories/conversations.py`: the only code that queries conversations/messages; every lookup takes `user_id`.
- Endpoints `/api/conversations` (list, create, get, rename, delete) and `/api/conversations/{id}/messages` (chat). The old in-memory `/api/chat` is gone.
- Every question and answer is saved; every model call (failed ones too) goes into `llm_calls`.
- The chat page starts a conversation, then sends messages into it. Chats now survive a backend restart.

**What I learned**
- **Repository pattern:** queries live in one place and always take `user_id`, so forgetting the filter is visible. "Not yours" and "doesn't exist" both give 404.
- **Transactions:** repositories don't commit; each request commits once. The question, the answer and the call log are saved together, or not at all.
- **N+1 queries:** touching `.messages` on N conversations in a loop runs 1 + N queries. `lazy="raise"` makes that an error; `selectinload` loads them all in one extra query.
- **Don't order by timestamps:** Windows gave 99,986 of 100,000 back-to-back timestamps the same value. A `position` column with a UNIQUE constraint orders messages exactly.
- **Read autogenerated migrations:** the constraint name only named the first column, and a NOT NULL column without a default would fail on a table with rows.
- `pre-commit run --all-files` only checks files git knows about: `git add` new files first.
- `uvicorn` without `--reload` keeps running old code after you change files. Check what a server is actually running before trusting a manual test.

**What confused me**
- …

---

## SMA-31 — Sidebar conversation history with auto-generated titles
**Date:** 16 Nov 2026

**What I did**
- "Recent chats" in the sidebar: open, rename, delete (with a confirmation), plus a New chat button.
- Each chat has its own address (`/c/<id>`): a reload keeps it, and reopening it picks its model again.
- New chats get a short AI title after the first answer (or the first words if the AI fails).

**What I learned**
- **Test the real model before choosing settings:** with a 20–60 token budget, both thinking models returned *nothing*. They need ~300 tokens even for a 5-word answer.
- **Don't make the user wait for extras:** the title is a separate call after the answer, so the answer isn't slowed down.
- **React Query cache keys:** the sidebar list and the open chat use different keys, so refreshing one never refetches the other. Adding the new turn to the cache means no refetch at all.
- **The URL as state:** `/c/<id>` makes chats reloadable and linkable. A React `key` decides when a page starts fresh (New chat) and when it must keep its state (moving a new chat to its address).
- **Small UX traps:** saving a rename on blur would also save when Escape closes the box; a prompt's instructions can leak into the output ("in One Sentence").

**What confused me**
- …
