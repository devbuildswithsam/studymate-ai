# Vercel PoC (SMA-18) — results

- Date:
- Backend URL:
- Web URL:
- Entry file Vercel found: `main.py` (variable `app`)
- Python version in build log:
- /api/health on Vercel: works / fails
- Streaming direct to backend (curl -N): one by one / all at once
- Streaming through the web rewrite: one by one / all at once
- First request after idle (cold start), seconds:
- Problems hit:
- Verdict: Vercel OK for the real app / use fallback host (guide Section 10.2)