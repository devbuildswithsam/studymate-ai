"""Chunking (guide 7.3 step 4): ~800 tokens, ~15% overlap, paragraph boundaries, page numbers.
SMA-45, test-first. Done when: these cover chunk sizes, overlap and page numbers.
"""

import re

from app.services.rag.chunk import (
    OVERLAP_CHARS,
    TARGET_CHARS,
    TARGET_TOKENS,
    chunk_pages,
    estimate_tokens,
)
from app.services.rag.extract import Page


def sentence(n: int) -> str:
    return f"Sentence {n} explains one more idea about heat, work and energy."  # ~65 chars


def paragraph(first: int, count: int) -> str:
    return " ".join(sentence(n) for n in range(first, first + count))


def ten_pages() -> list[Page]:
    """The guide's test: a 10-page text, 3 paragraphs of 5 sentences per page."""
    pages, n = [], 0
    for number in range(1, 11):
        paragraphs = []
        for _ in range(3):
            paragraphs.append(paragraph(n, 5))
            n += 5
        pages.append(Page(number, "\n\n".join(paragraphs)))
    return pages


def overlap_of(first: str, second: str) -> str:
    """The longest end of `first` that `second` starts with."""
    for size in range(min(len(first), len(second)), 0, -1):
        if first.endswith(second[:size]):
            return second[:size]
    return ""


def test_the_settings_match_the_guide():
    assert TARGET_TOKENS == 800
    assert TARGET_CHARS == 3000  # ~800 tokens (guide: "about 800 tokens (~3,000 characters)")
    assert OVERLAP_CHARS == 450  # 15%


# --- Done when: chunk sizes -------------------------------------------------------------------


def test_a_ten_page_text_becomes_chunks_of_about_800_tokens():
    chunks = chunk_pages(ten_pages())

    total = sum(len(p.text) for p in ten_pages())
    assert total // TARGET_CHARS <= len(chunks) <= total // (TARGET_CHARS - OVERLAP_CHARS) + 1
    assert all(len(c.text) <= TARGET_CHARS for c in chunks)
    assert all(len(c.text) >= TARGET_CHARS * 0.6 for c in chunks[:-1])  # none tiny but the last
    assert all(c.token_count <= TARGET_TOKENS for c in chunks)


def test_token_counts_are_estimated_from_the_length():
    assert estimate_tokens("x" * 3000) == 800
    assert estimate_tokens("") == 0
    [chunk] = chunk_pages([Page(1, paragraph(0, 3))])
    assert chunk.token_count == estimate_tokens(chunk.text)


def test_chunks_are_numbered_in_reading_order():
    chunks = chunk_pages(ten_pages())

    assert [c.index for c in chunks] == list(range(len(chunks)))
    per_chunk = [[int(n) for n in re.findall(r"Sentence (\d+)", c.text)] for c in chunks]
    assert sorted({n for numbers in per_chunk for n in numbers}) == list(range(150))  # none lost
    assert all(numbers == sorted(numbers) for numbers in per_chunk)  # in order inside a chunk
    last_numbers = [numbers[-1] for numbers in per_chunk]
    assert last_numbers == sorted(set(last_numbers))  # each chunk reaches further


# --- Done when: overlap -----------------------------------------------------------------------


def test_each_chunk_starts_with_the_last_15_percent_of_the_one_before():
    chunks = chunk_pages(ten_pages())

    for before, after in zip(chunks, chunks[1:], strict=False):
        shared = overlap_of(before.text, after.text)
        assert 0.10 * TARGET_CHARS <= len(shared) <= OVERLAP_CHARS
        assert shared.startswith("Sentence")  # the overlap starts at a sentence, not mid-word


def test_a_short_document_is_one_chunk_without_overlap():
    chunks = chunk_pages([Page(None, "# Notes\n\nEntropy always increases.")])

    assert [(c.index, c.page, c.text) for c in chunks] == [
        (0, None, "# Notes\n\nEntropy always increases.")
    ]


def test_no_text_means_no_chunks():
    assert chunk_pages([]) == []


# --- Paragraph boundaries ----------------------------------------------------------------------


def test_paragraphs_are_never_cut_in_two():
    chunks = chunk_pages(ten_pages())
    paragraphs = [p for page in ten_pages() for p in page.text.split("\n\n")]

    for p in paragraphs:
        assert any(p in c.text for c in chunks), f"paragraph cut: {p[:40]}..."


def test_a_paragraph_too_long_for_one_chunk_is_split_between_sentences():
    long_paragraph = paragraph(0, 120)  # ~7,800 characters, no blank line at all

    chunks = chunk_pages([Page(1, long_paragraph)])

    assert len(chunks) >= 3
    assert all(len(c.text) <= TARGET_CHARS for c in chunks)
    assert all(c.text.endswith("energy.") for c in chunks)  # each ends at a sentence end


def test_a_huge_sentence_is_split_between_words():
    words = " ".join(f"word{n}" for n in range(2000))  # ~15,000 characters, no full stop

    chunks = chunk_pages([Page(1, words)])

    assert all(len(c.text) <= TARGET_CHARS for c in chunks)
    for c in chunks:
        assert all(re.fullmatch(r"word\d+", w) for w in c.text.split())  # no word cut


# --- Done when: page numbers --------------------------------------------------------------------


def test_each_chunk_keeps_the_page_its_new_text_starts_on():
    pages = [Page(n, paragraph(100 * n, 30)) for n in (1, 2, 3)]  # ~2,000 characters each

    chunks = chunk_pages(pages)

    assert [c.page for c in chunks] == [1, 2, 3]
    assert "Sentence 100 " in chunks[0].text and "Sentence 200 " in chunks[1].text


def test_page_numbers_follow_the_real_pdf_pages():
    # Page 2 had no text (skipped by extraction): the numbers still match the PDF.
    pages = [Page(1, paragraph(0, 30)), Page(3, paragraph(100, 30))]

    assert [c.page for c in chunk_pages(pages)] == [1, 3]


def test_text_files_have_no_page_numbers():
    chunks = chunk_pages([Page(None, "\n\n".join(paragraph(10 * n, 6) for n in range(20)))])

    assert len(chunks) > 1
    assert {c.page for c in chunks} == {None}


def test_a_chunk_that_runs_over_two_pages_keeps_its_first_page():
    pages = [Page(4, paragraph(0, 8)), Page(5, paragraph(100, 15))]  # ~500 + ~1,000 characters

    [chunk] = chunk_pages(pages)

    assert chunk.page == 4
