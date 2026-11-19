"""Step 4 of ingestion: cut the clean text into chunks (guide 7.3). SMA-45.

Search compares a question with CHUNKS, so their shape matters:
- about 800 tokens (~3,000 characters): big enough to hold a whole idea, small enough
  that a match is precise and 5 of them fit in the model's prompt
- ~15% overlap: each chunk starts with the end of the previous one, so an idea that
  sits on a boundary is still whole in one of them
- split between paragraphs; a paragraph too long for one chunk is split between
  sentences, and a "sentence" too long (no full stops) between words
- each chunk keeps the page its new text starts on, for citations ("page 12")

Tokens are estimated from the length (the guide's ~3.75 characters per token): each
provider counts tokens a little differently, and an estimate is enough for sizing.
"""

import re
from dataclasses import dataclass

from app.services.rag.extract import Page

TARGET_TOKENS = 800
OVERLAP_SHARE = 0.15
CHARS_PER_TOKEN = 3.75
TARGET_CHARS = round(TARGET_TOKENS * CHARS_PER_TOKEN)  # 3000
OVERLAP_CHARS = round(TARGET_CHARS * OVERLAP_SHARE)  # 450
PARAGRAPH_BREAK = "\n\n"
# A piece must fit in a chunk that already starts with the overlap (and a joiner).
MAX_PIECE_CHARS = TARGET_CHARS - OVERLAP_CHARS - len(PARAGRAPH_BREAK)

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# Where a sentence or paragraph starts inside a chunk: a good place to begin the overlap.
SENTENCE_START = re.compile(r"(?<=[.!?])\s+|\n\n")


@dataclass(frozen=True)
class TextChunk:
    index: int  # 0, 1, 2... in reading order
    page: int | None  # where its new text starts; None for TXT / MD
    text: str
    token_count: int


@dataclass(frozen=True)
class _Piece:
    """A paragraph, or part of one when it's too long. Never longer than MAX_PIECE_CHARS."""

    page: int | None
    text: str
    starts_paragraph: bool


def estimate_tokens(text: str) -> int:
    return round(len(text) / CHARS_PER_TOKEN)


def chunk_pages(pages: list[Page]) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    text = ""  # the chunk being built
    page: int | None = None
    has_new_text = False  # False while it only holds the previous chunk's overlap

    def finish() -> None:
        chunks.append(TextChunk(len(chunks), page, text, estimate_tokens(text)))

    for piece in (p for page_ in pages for p in _pieces(page_)):
        joiner = PARAGRAPH_BREAK if piece.starts_paragraph else " "
        if has_new_text and len(text) + len(joiner) + len(piece.text) > TARGET_CHARS:
            finish()
            text, has_new_text = _overlap(text), False
        if not has_new_text:
            page = piece.page  # the page where this chunk's own text begins
        text = text + joiner + piece.text if text else piece.text
        has_new_text = True
    if has_new_text:
        finish()
    return chunks


def _pieces(page: Page) -> list[_Piece]:
    pieces = []
    for paragraph in page.text.split(PARAGRAPH_BREAK):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        parts = [paragraph] if len(paragraph) <= MAX_PIECE_CHARS else _split_long(paragraph)
        for i, part in enumerate(parts):
            pieces.append(_Piece(page.number, part, starts_paragraph=i == 0))
    return pieces


def _split_long(paragraph: str) -> list[str]:
    """Pack sentences into parts that fit; a sentence that can't fit is split between words."""
    sentences = []
    for sentence in SENTENCE_END.split(paragraph):
        sentences.extend([sentence] if len(sentence) <= MAX_PIECE_CHARS else _by_words(sentence))
    parts, current = [], ""
    for sentence in sentences:
        if current and len(current) + 1 + len(sentence) > MAX_PIECE_CHARS:
            parts.append(current)
            current = ""
        current = f"{current} {sentence}" if current else sentence
    return [*parts, current] if current else parts


def _by_words(text: str) -> list[str]:
    parts, current = [], ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > MAX_PIECE_CHARS:
            parts.append(current)
            current = ""
        current = f"{current} {word}" if current else word
    # A single "word" longer than a piece (very rare: a long URL) is cut by length.
    return [
        p[i : i + MAX_PIECE_CHARS]
        for p in [*parts, current]
        for i in range(0, len(p), MAX_PIECE_CHARS)
    ]


def _overlap(text: str) -> str:
    """The end of a finished chunk that the next one starts with: at most OVERLAP_CHARS,
    beginning at a sentence start if possible, else at a word."""
    for boundary in (SENTENCE_START, re.compile(r"\s+")):
        starts = [m.end() for m in boundary.finditer(text) if len(text) - m.end() <= OVERLAP_CHARS]
        if starts:
            return text[min(starts) :]  # the longest overlap that fits
    return ""
