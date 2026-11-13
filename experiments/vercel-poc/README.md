# Vercel PoC (SMA-18) — results

- **Date:** 13 Nov 2026
- **Backend URL:** https://studymate-ai-theta-one.vercel.app
- **Web URL:** https://studymate-ai-web-nu.vercel.app
- **Entry file Vercel found:** `main.py` (variable `app`), zero config — no `vercel.json` in the backend
- **Python version in build log:** 3.12
- **/api/health on Vercel:** works ✅
- **Streaming direct to backend (`curl -N`):** one by one, 0.5 s apart ✅
- **Streaming through the web rewrite (`/api/*` → backend):** one by one ✅ (client saw 0.55 s, 1.04 s … 5.04 s; done at 5.55 s)
- **First request after idle (cold start):** not measured
- **Problems hit:** none
- **Verdict:** Vercel is OK for the real app: FastAPI, SSE streaming and the frontend → backend rewrite all work on the free Hobby plan. Fallback hosts (guide §10.2) not needed so far.

## How it is set up
- Two Vercel projects from one GitHub repo, each with its own **Root Directory**:
  - backend → `experiments/vercel-poc/backend` (FastAPI, `requirements.txt`, `.python-version` = 3.12)
  - web → `experiments/vercel-poc/web` (static `index.html`; `vercel.json` rewrites `/api/:path*` to the backend)
- The page calls only relative paths (`/api/...`), the same pattern the real React app will use.

## Still to test later
- MCP over HTTP on Vercel (SMA-38)
- Streaming a real LLM answer, and file uploads up to 4 MB (v1.1)