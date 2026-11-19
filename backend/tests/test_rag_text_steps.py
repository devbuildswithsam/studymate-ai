"""Extract -> clean -> chunk on a real PDF, the way ingestion will run them (SMA-47). SMA-45.

The unit tests check each step alone; this one checks they fit together (layout mode's
padding and blank lines, then cleaning, then chunking).
"""

from app.services.rag.chunk import TARGET_CHARS, chunk_pages
from app.services.rag.clean import clean_pages
from app.services.rag.extract import extract_pages
from tests.pdf_maker import make_pdf

PDF = "application/pdf"


def lecture_page(number: int) -> str | None:
    if number == 5:
        return None  # a diagram page: an image, no text
    body = []
    for paragraph in range(3):
        lines = [
            f"Topic {number}.{paragraph} covers how heat and work change the energy of",
            "a system. Engineers use these thermo-",
            "dynamic ideas to design engines and fridges that waste less energy.",
        ] * 3
        body.append("\n".join(lines))
    return "\n".join(
        ["Physics 101 - Lecture Notes", *"\n\n".join(body).split("\n"), f"Page {number} of 10"]
    )


def test_a_ten_page_lecture_pdf_becomes_clean_chunks_with_pages():
    data = make_pdf([lecture_page(n) for n in range(1, 11)])

    extracted = extract_pages(data, PDF)
    chunks = chunk_pages(clean_pages(extracted.pages, PDF))

    assert extracted.page_count == 10
    text = "\n".join(c.text for c in chunks)
    assert "Physics 101" not in text  # the repeated header is gone
    assert "Page 3 of 10" not in text  # so is the footer
    assert "thermodynamic ideas" in text  # the split word is whole again
    assert "  " not in text.replace("\n\n", "")  # no layout padding left
    assert all(len(c.text) <= TARGET_CHARS for c in chunks)
    pages = [c.page for c in chunks]
    assert pages == sorted(pages) and 5 not in pages  # in order; the image page has no text
    assert "Topic 10.2" in chunks[-1].text  # nothing lost at the end
