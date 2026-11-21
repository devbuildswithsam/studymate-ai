"""One error shape for the whole API: {"error": {"code": ..., "message": ...}}. SMA-20.

FastAPI's defaults differ per error ({"detail": ...} vs a list of problems), so the
frontend would need special cases. These handlers make every error look the same.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# Short, stable codes the frontend can switch on (the message is for humans).
CODES_BY_STATUS = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",  # e.g. an AI action already used (SMA-43)
    413: "payload_too_large",  # upload over 4 MB (SMA-44)
    415: "unsupported_media_type",  # upload that isn't a real PDF / TXT / MD (SMA-44)
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


def error_response(
    status_code: int,
    message: str,
    code: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    code = code or CODES_BY_STATUS.get(status_code, "error")
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # The exception's headers are kept: e.g. Retry-After on a 429 (SMA-67).
    return error_response(exc.status_code, str(exc.detail), headers=exc.headers)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Turn pydantic's list of problems into one readable sentence.
    problems = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]
    return error_response(422, "; ".join(problems))


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Log the full traceback for us, but never send internals to the browser.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return error_response(500, "Something went wrong on our side.")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
