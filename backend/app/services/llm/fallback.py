"""FallbackManager: try the chosen model, then the next suitable one. SMA-22 (guide §7.5).

The rest of the app asks the manager, never an adapter directly. Every answer is
labelled with whether a fallback was used and why, so the UI can say so.
"""

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

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
class Attempt:
    """One real call to one model, successful or not: a row for the llm_calls log (SMA-30)."""

    model: str
    provider: str
    status: Literal["ok", "error"]
    error_type: str | None  # e.g. "rate_limited", "timeout"; None when status is "ok"
    latency_ms: int
    fallback_used: bool = False  # True when this isn't the model that was asked for
    tokens_in: int | None = None  # only known when the model answered
    tokens_out: int | None = None


@dataclass
class ChatResult:
    """An answer plus the label the UI shows ("answered by X because Y failed")."""

    response: ChatResponse
    requested_model: str
    fallback_used: bool
    fallback_reason: str | None  # e.g. "gemini-3.5-flash: rate-limited"
    attempts: list[Attempt] = field(default_factory=list)  # every call made, in order


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
        attempts: list[Attempt] = []
        for model in candidates:
            if self.is_rate_limited(model.id):
                # Skipped without calling it, so it's not an attempt.
                reasons.append(f"{model.id}: rate-limited (cooling down)")
                continue
            started = self.clock()
            is_fallback = model.id != candidates[0].id
            try:
                response = self._provider(model).chat(messages, options)
            except LLMError as e:
                attempts.append(
                    Attempt(
                        model.id,
                        model.provider,
                        "error",
                        _error_type(e),
                        self._ms(started),
                        is_fallback,
                    )
                )
                reasons.append(self._handle_failure(model, e))
            else:
                attempts.append(
                    Attempt(
                        model.id,
                        model.provider,
                        "ok",
                        None,
                        self._ms(started),
                        is_fallback,
                        response.tokens_in,
                        response.tokens_out,
                    )
                )
                return ChatResult(
                    response=response,
                    requested_model=candidates[0].id,
                    fallback_used=is_fallback,
                    fallback_reason="; ".join(reasons) or None,
                    attempts=attempts,
                )

        raise AllModelsFailedError(
            "no model could answer: " + "; ".join(reasons), reasons, attempts
        )

    def _ms(self, started: float) -> int:
        return round((self.clock() - started) * 1000)

    def _handle_failure(self, model: ModelConfig, e: LLMError) -> str:
        """React to one failed call; return the short reason shown to the user."""
        if isinstance(e, RateLimitedError):
            self._mark_rate_limited(model.id, e.retry_after)
            return f"{model.id}: rate-limited"
        if isinstance(e, LLMConfigError):
            # Won't fix itself: log loudly, but still try the next model for the user.
            logger.error("Config problem with %s: %s", model.id, e)
            return f"{model.id}: configuration error"
        logger.warning("%s failed: %s", model.id, e)
        return f"{model.id}: {_short_reason(e)}"


def _error_type(e: LLMError) -> str:
    """A stable label for llm_calls.error_type."""
    if isinstance(e, RateLimitedError):
        return "rate_limited"
    if isinstance(e, LLMConfigError):
        return "config_error"
    if isinstance(e, ProviderTimeoutError):
        return "timeout"
    if isinstance(e, ProviderUnavailableError):
        return "unavailable"
    return "error"


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
