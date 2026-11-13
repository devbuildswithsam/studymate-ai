"""The FastAPI app. Run from backend/:  uvicorn app.main:app --reload   SMA-20.

`app` is an ASGI application: uvicorn (the server) calls it for every request.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.config import APP_VERSION, get_settings
from app.errors import register_error_handlers

settings = get_settings()

app = FastAPI(title="StudyMate AI", version=APP_VERSION)

# CORS: the browser only lets our React app (FRONTEND_ORIGIN) read API responses.
# One explicit origin, never "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

register_error_handlers(app)

app.include_router(health.router)
