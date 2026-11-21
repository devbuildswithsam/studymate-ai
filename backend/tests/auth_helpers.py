"""Helpers for tests with real accounts (AUTH_MODE=jwt). SMA-57, SMA-58.

The `jwt_api` fixture itself lives in conftest.py; these are the plain functions and
constants it and the tests share.
"""

from app.config import Settings

SECRET = "test-secret-that-is-long-enough-1234567890"  # 42 characters
CSRF_COOKIE = "studymate_csrf"
CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
FRONTEND = "http://localhost:5173"  # the allowed origin in the test settings (the default)


def act_like_our_frontend(client) -> None:
    """On every POST/PUT/PATCH/DELETE, copy the CSRF cookie into the X-CSRF-Token header,
    as frontend/src/api/client.ts does (SMA-58). Set `client.auto_csrf = False` to act like
    another website, which can't read our cookies."""
    client.auto_csrf = True

    def add_csrf_header(request):
        token = client.cookies.get(CSRF_COOKIE)
        if client.auto_csrf and request.method in UNSAFE_METHODS and token:
            request.headers.setdefault(CSRF_HEADER, token)

    client.event_hooks["request"].append(add_csrf_header)


def jwt_settings(database_url: str = "sqlite://") -> Settings:
    return Settings(
        _env_file=None, env="test", auth_mode="jwt", jwt_secret=SECRET, database_url=database_url
    )


def register(api, email="Ada@Example.com", password="correct horse battery", name="Ada"):
    return api.post("/api/auth/register", json={"email": email, "password": password, "name": name})


def set_cookie_header(response, name: str) -> str:
    """The Set-Cookie line for one cookie (a login sets two: session and CSRF)."""
    lines = [line for line in response.headers.get_list("set-cookie") if line.startswith(name)]
    assert len(lines) == 1, f"expected one Set-Cookie for {name}, got {lines}"
    return lines[0]
