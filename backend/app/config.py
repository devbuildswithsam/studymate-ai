"""App settings, loaded from environment variables and backend/.env. SMA-20.

pydantic-settings checks the types when the app starts, so a typo in .env
fails loudly at startup instead of halfway through a request.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]  # app -> backend
APP_VERSION = "1.0.0"
MIN_SECRET_LENGTH = 32  # characters of JWT_SECRET (ADR-0009)


class Settings(BaseSettings):
    # Absolute path, so it works no matter which folder you start uvicorn from.
    # extra="ignore": .env may hold keys this class doesn't use (yet).
    # hide_input_in_errors: a settings error would otherwise print every value, API keys
    # included, into the terminal and logs (found in SMA-29).
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    env: Literal["development", "test", "production"] = "development"
    # local: one seeded user, this computer only (development). jwt: real accounts with a
    # session cookie (SMA-57, ADR-0009).
    auth_mode: Literal["local", "jwt"] = "local"
    # Signs the session tokens. Anyone who knows it can log in as anyone: keep it in .env.
    jwt_secret: SecretStr | None = None
    frontend_origin: str = "http://localhost:5173"
    # SMA-68: who may see the admin usage page, e.g. "you@example.com, other@example.com".
    # Empty = nobody (in AUTH_MODE=local, the local user is the admin).
    admin_emails: str = ""
    # SQLite file next to where you start the app (run uvicorn/alembic from backend/). SMA-27.
    database_url: str = "sqlite:///./app.db"

    # SecretStr hides the value when printed or logged: Settings() shows '**********'.
    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None

    @model_validator(mode="after")
    def local_auth_only_in_development(self) -> "Settings":
        # AUTH_MODE=local trusts every request as one user: never allow it outside dev.
        if self.auth_mode == "local" and self.env == "production":
            raise ValueError("AUTH_MODE=local is not allowed when ENV=production")
        return self

    @model_validator(mode="after")
    def jwt_mode_needs_a_strong_secret(self) -> "Settings":
        # A short or missing secret could be guessed, and then any token could be forged.
        if self.auth_mode == "jwt":
            secret = self.jwt_secret.get_secret_value() if self.jwt_secret else ""
            if len(secret) < MIN_SECRET_LENGTH:
                raise ValueError(
                    f"AUTH_MODE=jwt needs JWT_SECRET in backend/.env, at least "
                    f"{MIN_SECRET_LENGTH} characters. Make one with: "
                    'python -c "import secrets; print(secrets.token_urlsafe(48))"'
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """Read the settings once and reuse them (also used as a FastAPI dependency)."""
    return Settings()


def app_settings(scope: dict) -> Settings:
    """The settings for code that runs outside a route (/mcp, middleware), honouring the
    same override tests use for every route. `scope` is the ASGI request scope."""
    fastapi_app = scope["app"]
    return fastapi_app.dependency_overrides.get(get_settings, get_settings)()
