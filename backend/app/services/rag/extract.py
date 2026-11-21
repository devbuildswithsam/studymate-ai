"""Step 2 of ingestion: get the text out of an upload, page by page (guide 7.3). SMA-45.

PDFs: pypdf, in "layout" mode. A PDF has no paragraph characters, only positioned lines;
layout mode turns a bigger vertical gap into a blank line, which is how the chunker finds
paragraphs. The price: it pads lines with spaces to copy the layout (clean.py removes them).

A scanned PDF is pictures of pages: there is no text to extract (we don't do OCR in v1.0),
so it is rejected with a clear message instead of becoming an empty document.

DOCX (SMA-66): python-docx. Word has no fixed pages (they depend on the printer and the
font), so the document is cut into SECTIONS at its headings, numbered 1, 2, 3...; that
number goes where a PDF's page number goes, and citations say "section 2". A DOCX without
headings has no numbers, like a TXT file. Tables are kept, one "cell | cell" line per row.
"""

import io
import logging
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.models.document import DOCX_TYPE

# Fewer letters than this in the whole file = no real text (a scan with page numbers
# stamped on it has digits, but no words).
MIN_LETTERS = 20
NO_TEXT = (
    "No text found: this looks like a scanned (image-only) document. "
    "Upload a PDF with selectable text."
)
NO_TEXT_DOCX = "No text found: this document is empty."

logging.getLogger("pypdf").setLevel(logging.ERROR)  # broken PDFs log noisy warnings


class ExtractionError(Exception):
    """The file's text can't be used. The message is shown to the student."""


@dataclass(frozen=True)
class Page:
    number: int | None  # 1, 2, 3... a PDF's page or a DOCX's section; None for TXT / MD
    text: str


@dataclass(frozen=True)
class Extracted:
    pages: list[Page]  # only pages that have text
    page_count: int | None  # every page of a PDF, with or without text; None otherwise


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
    elif mime_type == DOCX_TYPE:
        extracted = _docx_sections(data)
    else:
        text = data.decode("utf-8-sig")  # -sig: drops Notepad's byte order mark
        extracted = Extracted([Page(None, text)], None)
    letters = sum(ch.isalpha() for page in extracted.pages for ch in page.text)
    if letters < MIN_LETTERS:
        raise ExtractionError(NO_TEXT_DOCX if mime_type == DOCX_TYPE else NO_TEXT)
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


def location_word(filename: str) -> str:
    """What a location number means: a DOCX's is a section, anything else's a page. The
    name can be trusted here: the upload check made sure it matches the content."""
    return "section" if filename.lower().endswith(".docx") else "page"


def _docx_sections(data: bytes) -> Extracted:
    try:
        return _read_sections(docx.Document(io.BytesIO(data)))
    except Exception as e:  # noqa: BLE001 - a damaged file breaks python-docx in many ways
        raise ExtractionError("This DOCX can't be read: it may be damaged.") from e


def _read_sections(document) -> Extracted:
    sections: list[list[str]] = [[]]  # the paragraphs of each section
    has_headings = False
    for block in document.iter_inner_content():  # paragraphs and tables, in document order
        if isinstance(block, Table):
            rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in block.rows]
            sections[-1].append("\n".join(rows))
        elif isinstance(block, Paragraph) and block.text.strip():
            if _is_heading(block):
                has_headings = True
                if sections[-1]:  # a heading starts the next section
                    sections.append([])
            sections[-1].append(block.text.strip())
    texts = ["\n\n".join(paragraphs) for paragraphs in sections if paragraphs]
    if not has_headings:
        return Extracted([Page(None, text) for text in texts], None)
    return Extracted([Page(n, text) for n, text in enumerate(texts, start=1)], None)


def _is_heading(paragraph: Paragraph) -> bool:
    """Word's built-in "Heading 1", "Heading 2"... and "Title" styles."""
    style = paragraph.style.name if paragraph.style is not None else ""
    return style.startswith("Heading") or style == "Title"


def run_to_end[T](steps: Generator[Any, None, T]) -> T:
    """Run a step generator, ignoring its progress, and return its result."""
    while True:
        try:
            next(steps)
        except StopIteration as finished:
            return finished.value
