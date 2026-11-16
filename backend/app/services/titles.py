"""Short conversation titles for the sidebar. SMA-31.

The AI writes one from the first message. If it can't (every model failed, or the answer
is unusable), the first few words of the message are used instead.
"""

import re
from dataclasses import dataclass

from app.services.llm.base import ChatOptions
from app.services.llm.exceptions import LLMError
from app.services.llm.fallback import Attempt, FallbackManager

TITLE_PROMPT = (
    "Write a short title (3 to 6 words) for a study chat that starts with the user's "
    "message. Name the topic only, not how to answer (leave out things like 'in one "
    "sentence' or 'step by step'). Reply with the title only: no quotes, no full stop."
)
# Thinking models (Gemini 3.5 Flash, GPT-OSS) spend tokens on hidden reasoning before
# they write. In the SMA-31 probe, 20 and 60 tokens gave empty answers; 300 worked.
TITLE_MAX_TOKENS = 300
MAX_MESSAGE_CHARS = 500  # the start of the first message is enough to name the chat
MAX_TITLE_CHARS = 60
FALLBACK_WORDS = 6


@dataclass
class TitleResult:
    title: str
    attempts: list[Attempt]  # every model call made, for the llm_calls log


def generate_title(
    manager: FallbackManager, first_message: str, model_id: str | None = None
) -> TitleResult:
    messages = [
        {"role": "system", "content": TITLE_PROMPT},
        {"role": "user", "content": first_message[:MAX_MESSAGE_CHARS]},
    ]
    options = ChatOptions(max_tokens=TITLE_MAX_TOKENS, temperature=0)
    try:
        result = manager.chat(messages, options, model_id)
    except LLMError as e:  # every model failed, or the chosen one is disabled
        return TitleResult(fallback_title(first_message), getattr(e, "attempts", []))
    title = clean_title(result.response.text) or fallback_title(first_message)
    return TitleResult(title, result.attempts)


def fallback_title(message: str) -> str:
    """The first few words of the message."""
    words = message.split()  # split() also drops line breaks and repeated spaces
    title = " ".join(words[:FALLBACK_WORDS])
    if len(words) > FALLBACK_WORDS:
        title += "…"
    return shorten(title)


def clean_title(text: str) -> str | None:
    """Tidy what the AI wrote: first line, no Markdown, quotes, label or full stop."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return None
    title = re.sub(r"[*#`_]", "", lines[0])  # Markdown like **bold** or # heading
    title = re.sub(r"^\s*title\s*:\s*", "", title, flags=re.IGNORECASE)  # "Title: ..."
    title = " ".join(title.split()).strip("\"'“”‘’ ").rstrip(".:;,")
    return shorten(title) if title else None


def shorten(text: str, limit: int = MAX_TITLE_CHARS) -> str:
    """Cut to `limit` characters, between words when possible, ending with '…'."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip() + "…"
