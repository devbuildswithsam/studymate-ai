"""Google Gemini, through its OpenAI-compatible endpoint. SMA-21.

Gemini-specific behaviour lives here. Guide §7.5: Gemini's compatibility layer has
gaps (tool calling, JSON), so fixes for those (Stage 3) go in this class too.
"""

import re

import openai

from app.services.llm.exceptions import LLMConfigError, LLMError
from app.services.llm.openai_compat import OpenAICompatibleProvider


class GeminiProvider(OpenAICompatibleProvider):
    name = "gemini"

    def _error_from_status(self, e: openai.APIStatusError) -> LLMError:
        # Quirk (SMA-54): a wrong API key is HTTP 400 INVALID_ARGUMENT here, not 401/403.
        # Gemini uses that same 400 for ordinary bad requests, so the message decides.
        # Only a key problem is a config error; every other 400 stays a normal error.
        if e.status_code == 400 and self._is_bad_key(e):
            message = f"{self.name} HTTP 400: {self._error_message(e)}"
            return LLMConfigError(message, self.name, 400)
        return super()._error_from_status(e)

    def _is_bad_key(self, e: openai.APIStatusError) -> bool:
        # "Please pass a valid API key" (seen live) or Google's API_KEY_INVALID reason.
        mentions_key = "api key" in self._error_message(e).lower()
        return mentions_key or "API_KEY_INVALID" in e.response.text

    @staticmethod
    def _retry_after(e: openai.APIStatusError) -> float | None:
        # Quirk: on 429 Google usually puts the wait in the body ("retryDelay": "17s"),
        # not in the standard Retry-After header. Check the header first, then the body.
        seconds = OpenAICompatibleProvider._retry_after(e)
        if seconds is not None:
            return seconds
        match = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', e.response.text)
        return float(match.group(1)) if match else None
