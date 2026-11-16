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
APP_VERSION = "0.1.0"


class Settings(BaseSettings):
    # Absolute path, so it works no matter which folder you start uvicorn from.
    # extra="ignore": .env may hold keys this class doesn't use (yet).
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: Literal["development", "test", "production"] = "development"
    auth_mode: Literal["local"] = "local"  # real auth arrives in Stage 5
    frontend_origin: str = "http://localhost:5173"
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


@lru_cache
def get_settings() -> Settings:
    """Read the settings once and reuse them (also used as a FastAPI dependency)."""
    return Settings()
