"""FallbackManager: try the chosen model, then the next suitable one. SMA-22 (guide §7.5).

The rest of the app asks the manager, never an adapter directly. Every answer is
labelled with whether a fallback was used and why, so the UI can say so.
"""

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache

from app.config import get_settings
from app.services.llm.base import Capability, ChatOptions, ChatResponse, LLMProvider, Message
from app.services.llm.exceptions import (
    AllModelsFailedError,
    LLMConfigError,
    LLMError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.services.llm.factory import build_provider
from app.services.llm.registry import ModelConfig, ModelRegistry, get_registry

logger = logging.getLogger(__name__)

DEFAULT_COOLDOWN_SECONDS = 60  # how long to skip a model after a 429 with no wait time


@dataclass
class ChatResult:
    """An answer plus the label the UI shows ("answered by X because Y failed")."""

    response: ChatResponse
    requested_model: str
    fallback_used: bool
    fallback_reason: str | None  # e.g. "gemini-3.5-flash: rate-limited"


class FallbackManager:
    def __init__(
        self,
        registry: ModelRegistry,
        provider_factory: Callable[[ModelConfig], LLMProvider],
        clock: Callable[[], float] = time.monotonic,  # tests pass a fake clock
    ):
        self.registry = registry
        self.provider_factory = provider_factory
        self.clock = clock
        self._providers: dict[str, LLMProvider] = {}  # built once per model, then reused
        self._rate_limited_until: dict[str, float] = {}  # model id -> clock time

    # --- Rate-limit memory ------------------------------------------------------

    def is_rate_limited(self, model_id: str) -> bool:
        return self.clock() < self._rate_limited_until.get(model_id, 0)

    def _mark_rate_limited(self, model_id: str, retry_after: float | None) -> None:
        wait = retry_after if retry_after is not None else DEFAULT_COOLDOWN_SECONDS
        self._rate_limited_until[model_id] = self.clock() + wait

    # --- Choosing models --------------------------------------------------------

    def candidates(
        self, model_id: str | None = None, needs: Iterable[Capability] = ()
    ) -> list[ModelConfig]:
        """Models to try, in order: the chosen one first, then enabled models by priority.

        Only models with EVERY needed capability are included: a tools request must
        never fall back to a model that can't call tools.
        """
        needs = set(needs)

        def suitable(m: ModelConfig) -> bool:
            return all(m.supports(c) for c in needs)

        if model_id is not None:
            chosen = self.registry.get(model_id)
            if not chosen.enabled:
                raise LLMConfigError(f"model {model_id!r} is disabled", chosen.provider)
            if not suitable(chosen):
                missing = sorted(c for c in needs if not chosen.supports(c))
                raise LLMConfigError(
                    f"model {model_id!r} does not support {', '.join(missing)}", chosen.provider
                )
            others = [m for m in self.registry.enabled_models() if m.id != model_id]
            return [chosen] + [m for m in others if suitable(m)]
        return [m for m in self.registry.enabled_models() if suitable(m)]

    def _provider(self, model: ModelConfig) -> LLMProvider:
        if model.id not in self._providers:
            self._providers[model.id] = self.provider_factory(model)
        return self._providers[model.id]

    # --- The main call ----------------------------------------------------------

    def chat(
        self,
        messages: list[Message],
        options: ChatOptions | None = None,
        model_id: str | None = None,
        needs: Iterable[Capability] = (),
        allow_fallback: bool = True,  # False: try only the chosen model (SMA-26 toggle)
    ) -> ChatResult:
        candidates = self.candidates(model_id, needs)
        if not allow_fallback:
            candidates = candidates[:1]
        if not candidates:
            raise AllModelsFailedError(
                f"no enabled model supports {', '.join(sorted(set(needs)))}", reasons=[]
            )

        reasons: list[str] = []
        for model in candidates:
            if self.is_rate_limited(model.id):
                reasons.append(f"{model.id}: rate-limited (cooling down)")
                continue
            try:
                response = self._provider(model).chat(messages, options)
            except RateLimitedError as e:
                self._mark_rate_limited(model.id, e.retry_after)
                reasons.append(f"{model.id}: rate-limited")
            except LLMConfigError as e:
                # Won't fix itself: log loudly, but still try the next model for the user.
                logger.error("Config problem with %s: %s", model.id, e)
                reasons.append(f"{model.id}: configuration error")
            except LLMError as e:
                logger.warning("%s failed: %s", model.id, e)
                reasons.append(f"{model.id}: {_short_reason(e)}")
            else:
                return ChatResult(
                    response=response,
                    requested_model=candidates[0].id,
                    fallback_used=model.id != candidates[0].id,
                    fallback_reason="; ".join(reasons) or None,
                )

        raise AllModelsFailedError("no model could answer: " + "; ".join(reasons), reasons)


def _short_reason(e: LLMError) -> str:
    """A short, user-safe reason (the full error goes to the log)."""
    if isinstance(e, ProviderTimeoutError):
        return "timed out"
    if isinstance(e, ProviderUnavailableError):
        return "unavailable"
    return "error"


@lru_cache
def get_fallback_manager() -> FallbackManager:
    """One manager for the whole app, so the rate-limit memory is shared.

    Also a FastAPI dependency: tests override it with fake providers.
    """
    registry = get_registry()
    settings = get_settings()
    return FallbackManager(registry, lambda m: build_provider(m, registry, settings))
