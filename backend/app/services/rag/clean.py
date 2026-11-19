"""Step 3 of ingestion: clean the extracted text (guide 7.3). SMA-45.

The output keeps one rule the chunker relies on: paragraphs are separated by exactly one
blank line ("\n\n").

PDFs need the most work, because a PDF stores positioned LINES, not flowing text:
- words split at a line end ("thermo-" + "dynamics") are joined again
- the lines of a paragraph are joined with spaces; layout padding is removed
- a header or footer repeated on most pages ("Physics Notes", "Page 3 of 34") is dropped,
  and so are bare page numbers: they would only add noise to every chunk
TXT / MD keep their line breaks (Markdown lists and headings depend on them).
"""

import re

from app.services.rag.extract import Page

MIN_PAGES_FOR_REPEATS = 3  # with fewer pages, "repeated on every page" proves nothing
REPEATED_SHARE = 0.6  # a top/bottom line on at least 60% of pages is a header/footer
# "12", "- 12 -", "Page 12", "Page 12 of 34", "12 / 34"
PAGE_NUMBER = re.compile(r"^(page\s*)?[-–—\s]*\d+(\s*(of|/)\s*\d+)?[-–—\s]*$", re.IGNORECASE)


def clean_pages(pages: list[Page], mime_type: str) -> list[Page]:
    if mime_type == "application/pdf":
        cleaned = _clean_pdf(pages)
    else:
        cleaned = [Page(p.number, _clean_text_file(p.text)) for p in pages]
    return [p for p in cleaned if p.text]  # a page that was only a header is gone


# --- Text files ------------------------------------------------------------------------------


def _clean_text_file(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# --- PDFs ------------------------------------------------------------------------------------


def _clean_pdf(pages: list[Page]) -> list[Page]:
    lines_per_page = [[_squeeze(line) for line in p.text.split("\n")] for p in pages]
    top, bottom = _repeated_edges(lines_per_page)
    cleaned = []
    for page, lines in zip(pages, lines_per_page, strict=True):
        lines = _drop_edges(lines, top, bottom)
        cleaned.append(Page(page.number, "\n\n".join(_paragraphs(lines))))
    return cleaned


def _squeeze(line: str) -> str:
    """Remove layout padding: runs of spaces/tabs become one space."""
    return re.sub(r"[ \t]+", " ", line).strip()


def _key(line: str) -> str:
    """Lines that differ only in numbers ("Page 3 of 9", "Page 4 of 9") are the same line.

    Known limit: if most pages START with such a line ("Exercise 1", "Exercise 2"...),
    it is taken for a header and dropped too. Rare in study notes; accepted for v1.0.
    """
    return re.sub(r"\d+", "#", line.lower())


def _first_and_last(lines: list[str]) -> tuple[str | None, str | None]:
    text_lines = [line for line in lines if line]
    return (text_lines[0], text_lines[-1]) if text_lines else (None, None)


def _repeated_edges(lines_per_page: list[list[str]]) -> tuple[set[str], set[str]]:
    """The first lines (headers) and last lines (footers) repeated on most pages."""
    if len(lines_per_page) < MIN_PAGES_FOR_REPEATS:
        return set(), set()
    edges = [_first_and_last(lines) for lines in lines_per_page]
    needed = REPEATED_SHARE * len(lines_per_page)

    def repeated(found: list[str | None]) -> set[str]:
        keys = [_key(line) for line in found if line]
        return {k for k in set(keys) if keys.count(k) >= needed}

    return repeated([e[0] for e in edges]), repeated([e[1] for e in edges])


def _drop_edges(lines: list[str], top: set[str], bottom: set[str]) -> list[str]:
    lines = list(lines)
    first = next((i for i, line in enumerate(lines) if line), None)
    if first is not None and (_key(lines[first]) in top or PAGE_NUMBER.match(lines[first])):
        lines[first] = ""
    last = next((i for i in range(len(lines) - 1, -1, -1) if lines[i]), None)
    if last is not None and (_key(lines[last]) in bottom or PAGE_NUMBER.match(lines[last])):
        lines[last] = ""
    return lines


def _paragraphs(lines: list[str]) -> list[str]:
    """Blank lines separate paragraphs; a paragraph's lines are joined into one."""
    paragraphs: list[str] = []
    current = ""
    for line in lines:
        if not line:
            if current:
                paragraphs.append(current)
            current = ""
        else:
            current = _join(current, line) if current else line
    if current:
        paragraphs.append(current)
    return paragraphs


def _join(text: str, line: str) -> str:
    if len(text) >= 2 and text.endswith("-") and text[-2].isalpha() and line[0].isalpha():
        # "thermo-" + "dynamics": a word split at the line end. Before a capital it's a
        # real hyphen ("Anglo-" + "Saxon"): keep it, but still no space.
        return text[:-1] + line if line[0].islower() else text + line
    return f"{text} {line}"
