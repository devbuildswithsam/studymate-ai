"""Load the model registry (models.yaml) and build clients. SMA-17.

Pydantic validation and the FallbackManager come in SMA-22.
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI

REGISTRY_PATH = Path(__file__).with_name("models.yaml")
BACKEND_DIR = Path(__file__).resolve().parents[3]  # llm -> services -> app -> backend


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def enabled_models(registry: dict) -> list[dict]:
    """Enabled models, in the order they should be tried."""
    models = [m for m in registry["models"] if m.get("enabled", True)]
    return sorted(models, key=lambda m: m["priority"])


def client_for(registry: dict, provider: str, max_retries: int = 2) -> OpenAI:
    """An OpenAI-compatible client for one provider, using its key from backend/.env."""
    load_dotenv(BACKEND_DIR / ".env")
    cfg = registry["providers"][provider]
    api_key = os.getenv(cfg["api_key_env"])
    if not api_key:
        raise RuntimeError(f"Missing {cfg['api_key_env']} in backend/.env")
    return OpenAI(base_url=cfg["base_url"], api_key=api_key, timeout=60, max_retries=max_retries)