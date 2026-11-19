"""Getting the text out of an upload, page by page (guide 7.3 step 2). SMA-45, test-first.

The PDFs are real ones, written by tests/pdf_maker.py.
"""

import io

import pytest
from pypdf import PdfReader, PdfWriter

from app.services.rag.extract import ExtractionError, extract_pages
from tests.pdf_maker import make_pdf

PDF = "application/pdf"


def test_a_pdf_gives_one_page_of_text_per_page_with_its_number():
    data = make_pdf(["Entropy always increases.", "Heat flows from hot to cold."])

    extracted = extract_pages(data, PDF)

    assert extracted.page_count == 2
    assert [p.number for p in extracted.pages] == [1, 2]
    assert "Entropy always increases." in extracted.pages[0].text
    assert "Heat flows from hot to cold." in extracted.pages[1].text


def test_a_gap_between_paragraphs_becomes_a_blank_line():
    # Layout mode keeps the vertical gap; plain extraction would lose the paragraph break.
    data = make_pdf(["First paragraph.\n\nSecond paragraph."])

    text = extract_pages(data, PDF).pages[0].text

    assert "First paragraph.\n\nSecond paragraph." in text


def test_a_page_without_text_in_a_normal_pdf_is_skipped_but_counted():
    data = make_pdf(["The first law of thermodynamics.", None, "The second law of thermodynamics."])

    extracted = extract_pages(data, PDF)

    assert extracted.page_count == 3
    assert [p.number for p in extracted.pages] == [1, 3]  # page 3 keeps its real number


# --- Done when: the image-only case --------------------------------------------------------


def test_an_image_only_pdf_is_rejected_with_a_clear_message():
    data = make_pdf([None, None, None])  # like a scanned document: pictures, no text

    with pytest.raises(ExtractionError) as error:
        extract_pages(data, PDF)

    assert "No text found" in str(error.value)
    assert "scanned" in str(error.value)


def test_a_scan_with_only_page_numbers_is_still_image_only():
    data = make_pdf(["1", "2", "3"])  # numbers stamped on scanned pages: no real text

    with pytest.raises(ExtractionError, match="No text found"):
        extract_pages(data, PDF)


# --- PDFs that can't be read ---------------------------------------------------------------


def test_a_password_protected_pdf_is_rejected():
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(["Secret notes."]))))
    writer.encrypt("secret", algorithm="RC4-128")
    data = io.BytesIO()
    writer.write(data)

    with pytest.raises(ExtractionError, match="password"):
        extract_pages(data.getvalue(), PDF)


def test_a_broken_pdf_is_rejected():
    with pytest.raises(ExtractionError, match="can't be read"):
        extract_pages(b"%PDF-1.7\nthis is not really a PDF", PDF)


# --- Text files ------------------------------------------------------------------------------


@pytest.mark.parametrize("mime_type", ["text/plain", "text/markdown"])
def test_a_text_file_is_one_page_without_a_number(mime_type):
    text = "# Thermodynamics\n\nEntropy always increases in an isolated system."

    extracted = extract_pages(text.encode(), mime_type)

    assert extracted.page_count is None  # pages only exist in PDFs
    assert [(p.number, p.text) for p in extracted.pages] == [(None, text)]


def test_a_notepad_byte_order_mark_is_dropped():
    extracted = extract_pages("﻿Entropy always increases.".encode(), "text/plain")

    assert extracted.pages[0].text == "Entropy always increases."


def test_an_empty_text_file_has_no_text():
    with pytest.raises(ExtractionError, match="No text found"):
        extract_pages(b"   \n\n  ", "text/plain")


def test_a_pdf_locked_with_an_empty_password_opens_normally():
    # Common in real PDFs: "encrypted" only to restrict printing, it opens without asking.
    writer = PdfWriter(
        clone_from=PdfReader(io.BytesIO(make_pdf(["Open notes about heat and entropy."])))
    )
    writer.encrypt(user_password="", owner_password="owner", algorithm="RC4-128")
    data = io.BytesIO()
    writer.write(data)

    assert "Open notes about heat and entropy." in extract_pages(data.getvalue(), PDF).pages[0].text
