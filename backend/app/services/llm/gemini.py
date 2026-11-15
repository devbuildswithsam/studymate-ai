"""Google Gemini, through its OpenAI-compatible endpoint. SMA-21.

Gemini-specific behaviour lives here. Guide §7.5: Gemini's compatibility layer has
gaps (tool calling, JSON), so fixes for those (Stage 3) go in this class too.
"""

import re

import openai

from app.services.llm.openai_compat import OpenAICompatibleProvider


class GeminiProvider(OpenAICompatibleProvider):
    name = "gemini"

    @staticmethod
    def _retry_after(e: openai.APIStatusError) -> float | None:
        # Quirk: on 429 Google usually puts the wait in the body ("retryDelay": "17s"),
        # not in the standard Retry-After header. Check the header first, then the body.
        seconds = OpenAICompatibleProvider._retry_after(e)
        if seconds is not None:
            return seconds
        match = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', e.response.text)
        return float(match.group(1)) if match else None
