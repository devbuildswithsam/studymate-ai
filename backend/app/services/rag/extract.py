"""Step 2 of ingestion: get the text out of an upload, page by page (guide 7.3). SMA-45.

PDFs: pypdf, in "layout" mode. A PDF has no paragraph characters, only positioned lines;
layout mode turns a bigger vertical gap into a blank line, which is how the chunker finds
paragraphs. The price: it pads lines with spaces to copy the layout (clean.py removes them).

A scanned PDF is pictures of pages: there is no text to extract (we don't do OCR in v1.0),
so it is rejected with a clear message instead of becoming an empty document.
"""

import io
import logging
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

# Fewer letters than this in the whole file = no real text (a scan with page numbers
# stamped on it has digits, but no words).
MIN_LETTERS = 20
NO_TEXT = (
    "No text found: this looks like a scanned (image-only) document. "
    "Upload a PDF with selectable text."
)

logging.getLogger("pypdf").setLevel(logging.ERROR)  # broken PDFs log noisy warnings


class ExtractionError(Exception):
    """The file's text can't be used. The message is shown to the student."""


@dataclass(frozen=True)
class Page:
    number: int | None  # 1, 2, 3... in a PDF; None for TXT / MD (no pages)
    text: str


@dataclass(frozen=True)
class Extracted:
    pages: list[Page]  # only pages that have text
    page_count: int | None  # every page of a PDF, with or without text; None for TXT / MD


PageProgress = tuple[int, int]  # (pages done, pages in total)


def extract_pages(data: bytes, mime_type: str) -> Extracted:
    """All at once, without progress (tests and simple callers)."""
    return run_to_end(extract_steps(data, mime_type))


def extract_steps(data: bytes, mime_type: str) -> Generator[PageProgress, None, Extracted]:
    """Yields (page, pages) after each PDF page, then RETURNS the result (SMA-47).

    The ingest pipeline uses `extracted = yield from extract_steps(...)`: each progress
    tuple goes straight to the browser, and the return value lands in `extracted`.
    """
    if mime_type == "application/pdf":
        extracted = yield from _pdf_pages(data)
    else:
        text = data.decode("utf-8-sig")  # -sig: drops Notepad's byte order mark
        extracted = Extracted([Page(None, text)], None)
    letters = sum(ch.isalpha() for page in extracted.pages for ch in page.text)
    if letters < MIN_LETTERS:
        raise ExtractionError(NO_TEXT)
    return extracted


def _pdf_pages(data: bytes) -> Generator[PageProgress, None, Extracted]:
    try:
        reader = PdfReader(io.BytesIO(data))
        # Some PDFs are "encrypted" with an empty password: those open fine.
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractionError("This PDF is password-protected. Remove the password first.")
        pages = []
        total = len(reader.pages)
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text(extraction_mode="layout")
            if text.strip():
                pages.append(Page(number, text))
            yield (number, total)
        return Extracted(pages, total)
    except ExtractionError:
        raise
    except (PdfReadError, ValueError, KeyError) as e:  # broken files fail in many ways
        raise ExtractionError("This PDF can't be read: it may be damaged.") from e


def run_to_end[T](steps: Generator[Any, None, T]) -> T:
    """Run a step generator, ignoring its progress, and return its result."""
    while True:
        try:
            next(steps)
        except StopIteration as finished:
            return finished.value
