"""Our own LLM error types. SMA-21.

Every adapter turns its provider's errors into these, so the rest of the app
(and the FallbackManager in SMA-22) reacts to *what happened*, not *who said it*.
"""


class LLMError(Exception):
    """Base class: `except LLMError` catches every LLM failure."""

    def __init__(self, message: str, provider: str, status_code: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class RateLimitedError(LLMError):
    """HTTP 429: free-tier limit hit. Wait, or use another provider."""

    def __init__(self, message: str, provider: str, retry_after: float | None = None):
        super().__init__(message, provider, status_code=429)
        self.retry_after = retry_after  # seconds, if the provider told us


class ProviderUnavailableError(LLMError):
    """HTTP 5xx or no connection: provider is down or overloaded. Retry later or fall back."""


class ProviderTimeoutError(LLMError):
    """No answer in time. Retry later or fall back."""


class LLMConfigError(LLMError):
    """HTTP 401/403/404 (or Gemini's bad-key 400, SMA-54): wrong API key or model id.
    Retrying won't help; fix the config."""


class AllModelsFailedError(LLMError):
    """Every model that could answer the request failed (SMA-22). The message lists why."""

    def __init__(self, message: str, reasons: list[str]):
        super().__init__(message, provider="fallback")
        self.reasons = reasons
