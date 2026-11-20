"""CSRF protection for every route: Origin check + double-submit token. SMA-58.

The attack (cross-site request forgery): you're logged in to StudyMate and open another
website. It makes your browser send e.g. POST /api/notes to StudyMate, and the browser
attaches your cookies. CORS doesn't stop this: it only stops the other site READING the
answer, not SENDING the request.

Two locks, for unsafe methods only (GET must never change anything):
1. Origin check, in both auth modes: the browser says which site started the request.
   Anything but our frontend is refused. (Local mode trusts every request from this
   computer, and the browser is on this computer, so it needs this lock too.)
2. Double-submit token, in AUTH_MODE=jwt: login sets a `studymate_csrf` cookie that our
   JavaScript reads and sends back in the X-CSRF-Token header. Another site can make the
   browser send our cookies but can't read them, so it can't fill in the header.

A middleware (not a dependency in each route) so a route added later is covered too.
"""

import secrets
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings, app_settings
from app.errors import error_response

CSRF_COOKIE = "studymate_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
# Before login there is no session and no token yet; the Origin check still runs.
NO_TOKEN_PATHS = {"/api/auth/login", "/api/auth/register"}

BLOCKED_ORIGIN = "Blocked: this request didn't come from the StudyMate app."
BLOCKED_TOKEN = "Blocked: the security token is missing or wrong. Reload the page and try again."


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)  # 43 characters, unguessable


def origin_of(url: str) -> str:
    """'https://site.example/page?x=1' -> 'https://site.example'."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def origin_problem(request: Request, settings: Settings) -> str | None:
    """Refuse requests that a browser says came from another site.

    Origin first; without it the Referer. With neither (curl, scripts, tests) there is
    nothing to compare: in jwt mode the token below still protects.
    """
    origin = request.headers.get("origin")
    if origin is None and (referer := request.headers.get("referer")):
        origin = origin_of(referer)
    if origin is None:
        return None
    # "null" (sandboxed pages) and any other site fail this comparison.
    return None if origin == settings.frontend_origin.rstrip("/") else BLOCKED_ORIGIN


def token_problem(request: Request) -> str | None:
    """The header must equal the cookie. compare_digest takes the same time however many
    characters match, so the answer's timing can't leak the token bit by bit."""
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header:
        return BLOCKED_TOKEN
    if not secrets.compare_digest(cookie.encode(), header.encode()):
        return BLOCKED_TOKEN
    return None


class CsrfMiddleware:
    """Checks every unsafe request before any route runs."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS or is_mcp(scope["path"]):
            await self.app(scope, receive, send)
            return

        settings = app_settings(scope)
        request = Request(scope)  # reads headers and cookies only; the body is left alone
        problem = origin_problem(request, settings)
        if problem is None and settings.auth_mode == "jwt" and scope["path"] not in NO_TOKEN_PATHS:
            problem = token_problem(request)
        if problem:
            await error_response(403, problem)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def is_mcp(path: str) -> bool:
    # /mcp is for programs that send a Bearer token (SMA-61), never cookies, so a forged
    # browser request has nothing to ride on. It has its own checks.
    return path == "/mcp" or path.startswith("/mcp/")
