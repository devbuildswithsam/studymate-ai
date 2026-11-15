"""GET /api/models: the models the user can pick, and whether each works right now. SMA-22.

Feeds the model dropdown in the chat header. Never returns API keys.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.services.llm.fallback import FallbackManager, get_fallback_manager
from app.services.llm.registry import ModelRegistry, api_key_for, get_registry

router = APIRouter(prefix="/api", tags=["models"])

ModelStatus = Literal["available", "rate_limited", "no_key"]


class ModelInfo(BaseModel):
    id: str
    provider: str
    display_name: str
    supports_tools: bool
    supports_json: bool
    status: ModelStatus


class ModelsResponse(BaseModel):
    default_model: str | None  # pre-selected in the dropdown
    models: list[ModelInfo]


@router.get("/models", response_model=ModelsResponse)
def list_models(
    registry: Annotated[ModelRegistry, Depends(get_registry)],
    settings: Annotated[Settings, Depends(get_settings)],
    manager: Annotated[FallbackManager, Depends(get_fallback_manager)],
) -> ModelsResponse:
    models = []
    for m in registry.enabled_models():
        if not api_key_for(registry, m.provider, settings):
            status: ModelStatus = "no_key"
        elif manager.is_rate_limited(m.id):
            status = "rate_limited"
        else:
            status = "available"
        models.append(
            ModelInfo(
                id=m.id,
                provider=m.provider,
                display_name=m.display_name,
                supports_tools=m.supports("tools"),
                supports_json=m.supports("json"),
                status=status,
            )
        )
    default = next((m.id for m in registry.enabled_models() if "chat" in m.default_for), None)
    return ModelsResponse(default_model=default, models=models)
