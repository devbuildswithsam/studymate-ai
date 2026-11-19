"""Cleaning extracted text (guide 7.3 step 3). SMA-45, test-first.

Paragraphs come out separated by one blank line ("\n\n"): the chunker splits there.
"""

from app.services.rag.clean import clean_pages
from app.services.rag.extract import Page

PDF = "application/pdf"


def clean_pdf(*texts: str) -> list[str]:
    pages = [Page(n, t) for n, t in enumerate(texts, start=1)]
    return [p.text for p in clean_pages(pages, PDF)]


# --- PDF text ---------------------------------------------------------------------------


def test_a_word_split_over_two_lines_is_joined():
    assert clean_pdf("the study of thermo-\ndynamics and heat") == [
        "the study of thermodynamics and heat"
    ]


def test_a_real_hyphen_before_a_capital_letter_is_kept():
    assert clean_pdf("the Anglo-\nSaxon period") == ["the Anglo-Saxon period"]


def test_lines_of_a_paragraph_are_joined_and_paragraphs_kept_apart():
    text = "Heat flows from\nhot to cold.\n\n\n\nEntropy always\nincreases."

    assert clean_pdf(text) == ["Heat flows from hot to cold.\n\nEntropy always increases."]


def test_layout_padding_is_removed():
    assert clean_pdf("      Heat    flows   from hot\t to cold.     ") == [
        "Heat flows from hot to cold."
    ]


def test_a_header_and_footer_repeated_on_every_page_are_dropped():
    pages = [
        f"Physics Notes - Chapter 3\nContent of page {n} about heat.\nPage {n} of 4"
        for n in range(1, 5)
    ]

    assert clean_pdf(*pages) == [f"Content of page {n} about heat." for n in range(1, 5)]


def test_a_line_that_only_starts_one_page_is_kept():
    pages = ["Introduction\nWhy heat matters.", "Heat engines.", "Refrigerators.", "Summary."]

    assert clean_pdf(*pages)[0] == "Introduction Why heat matters."


def test_bare_page_numbers_at_the_top_or_bottom_are_dropped():
    assert clean_pdf("12\nHeat flows from hot to cold.\n- 13 -") == ["Heat flows from hot to cold."]


def test_a_short_document_keeps_its_repeated_lines():
    # With 2 pages, "repeated on every page" proves nothing: keep everything.
    assert clean_pdf("Thermodynamics\nFirst page.", "Thermodynamics\nSecond page.") == [
        "Thermodynamics First page.",
        "Thermodynamics Second page.",
    ]


def test_a_page_left_empty_by_cleaning_is_dropped():
    pages = clean_pages([Page(1, "Some real text here."), Page(2, "  7  ")], PDF)

    assert [p.number for p in pages] == [1]


# --- Text and Markdown files -----------------------------------------------------------------


def test_markdown_keeps_its_line_breaks():
    # Joining lines would break lists and headings.
    text = "# Normal forms\n- 1NF\n- 2NF  \n\n\n\nA new paragraph."

    [page] = clean_pages([Page(None, text)], "text/markdown")

    assert page.text == "# Normal forms\n- 1NF\n- 2NF\n\nA new paragraph."


def test_windows_line_endings_become_plain_newlines():
    [page] = clean_pages([Page(None, "Line one\r\nLine two\r\n\r\nNew paragraph")], "text/plain")

    assert page.text == "Line one\nLine two\n\nNew paragraph"


def test_a_footer_that_changes_only_in_its_numbers_is_dropped():
    bodies = ["Heat flows to cold.", "Work moves things.", "Entropy rises.", "Engines waste heat."]
    pages = [f"{body}\nUniversity Physics, slide {n}" for n, body in enumerate(bodies, start=1)]

    assert clean_pdf(*pages) == bodies
