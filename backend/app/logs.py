"""Structured JSON logs with a request id (SMA-68, guide Stage 5 "Logging & monitoring").

Every request gets an id. It is sent back in the `X-Request-ID` header and in every error
body, and it is on every log line written while the request runs, so "it said error,
reference 3f2a..." leads straight to the right lines in the logs.

One JSON object per line ({"time", "level", "logger", "message", "request_id", ...}):
easy to search and to load into a log tool, unlike free text.

What is NEVER logged: request or response bodies (passwords, document text, answers),
query strings (search words), cookies and headers (session tokens). As a second line of
defence, `redact()` masks anything that looks like a key or token in every message.
"""

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import IO, Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The id of the request being handled, or None outside a request. A ContextVar: each
# request (and each thread it starts with a copied context) sees its own value.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

HEADER = "X-Request-ID"
# An id sent by a proxy in front of us is kept, if it is short and harmless (no spaces or
# newlines that could forge extra log lines).
SAFE_INCOMING_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")

# Extra fields a log call may add with `extra={...}`; anything else is ignored.
EXTRA_FIELDS = ("method", "path", "status", "duration_ms")

SECRET_PATTERNS = [
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [hidden]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "[hidden-jwt]"),
    (re.compile(r"\bsmat_[A-Za-z0-9_-]+"), "[hidden-token]"),  # our MCP tokens (SMA-61)
    (re.compile(r"\bgsk_[A-Za-z0-9]+"), "[hidden-key]"),  # Groq keys
    (re.compile(r"\bAIza[A-Za-z0-9_-]+"), "[hidden-key]"),  # Google keys
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "[hidden-key]"),  # OpenAI-style keys
    (re.compile(r"(?i)\b(password|passwd|secret|api_key)(\s*[=:]\s*)\S+"), r"\1\2[hidden]"),
]


def redact(text: str) -> str:
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            # Read when the line is written, in the thread that writes it.
            "request_id": request_id_var.get(),
        }
        for name in EXTRA_FIELDS:
            if hasattr(record, name):
                entry[name] = getattr(record, name)
        if record.exc_info:
            entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False)


HANDLER_NAME = "studymate-json"


def configure_logging(stream: IO[str] | None = None, level: int = logging.INFO) -> None:
    """Send every log line, ours and uvicorn's, to `stream` (stdout) as JSON.

    Safe to call again: our own handler is replaced. With no stream (the app starting),
    the app owns the root logger, so other handlers go: the MCP library calls
    logging.basicConfig() when our MCP server is created, which would print every line a
    second time as plain text (seen in the live check). Tests pass a stream, and keep
    pytest's own handlers.
    """
    root = logging.getLogger()
    for old in [h for h in root.handlers if stream is None or h.get_name() == HANDLER_NAME]:
        root.removeHandler(old)
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    # uvicorn has its own handlers: make them write JSON too. Its access log is replaced
    # by ours (which has the request id), so it is switched off.
    for name in ("uvicorn", "uvicorn.error"):
        for h in logging.getLogger(name).handlers:
            h.setFormatter(JsonFormatter())
    logging.getLogger("uvicorn.access").disabled = True


access_logger = logging.getLogger("studymate.access")


class RequestIdMiddleware:
    """Gives each request an id, sends it back in a header, and logs one line per request.

    A plain ASGI middleware (not BaseHTTPMiddleware), so streamed answers keep streaming
    and the id stays set until the last byte is sent.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(HEADER.lower().encode(), b"").decode("latin-1")
        request_id = incoming if SAFE_INCOMING_ID.fullmatch(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500  # if the app fails before answering

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[HEADER] = request_id
            await send(message)

        crashed = False
        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            # A crash is answered by Starlette's outermost layer, AFTER this one, so the
            # id stays set for it (errors.py adds it to that 500). Each request runs in
            # its own task, so it can't leak into the next request.
            crashed = True
            raise
        finally:
            access_logger.info(
                "%s %s %s",
                scope["method"],
                scope["path"],
                status,
                extra={
                    "method": scope["method"],
                    "path": scope["path"],  # never the query string: it may hold search words
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                },
            )
            if not crashed:
                request_id_var.reset(token)
