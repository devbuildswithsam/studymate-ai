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
