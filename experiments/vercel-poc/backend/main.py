"""SMA-18: throwaway Vercel proof of concept. No database, no keys, no user data."""

import asyncio
import json
import time

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI(title="StudyMate AI - Vercel PoC")


@app.get("/")
def root():
    return {"message": "StudyMate AI PoC. Try /api/health or /api/stream-test"}


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "studymate-poc", "version": "0.0.1"}


@app.get("/api/stream-test")
async def stream_test():
    """Send 10 Server-Sent Events, 0.5 s apart, to prove streaming works."""

    async def events():
        for n in range(1, 11):
            yield f"data: {json.dumps({'n': n, 'sent_at': round(time.time(), 2)})}\n\n"
            await asyncio.sleep(0.5)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )