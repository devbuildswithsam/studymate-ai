"""Groq, through its OpenAI-compatible endpoint. SMA-21.

Groq follows the OpenAI error format and sends a standard Retry-After header on 429,
so the shared code already handles it. Groq-specific fixes go in this class.
"""

from app.services.llm.openai_compat import OpenAICompatibleProvider


class GroqProvider(OpenAICompatibleProvider):
    name = "groq"
