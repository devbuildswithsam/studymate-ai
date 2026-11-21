"""DOCX uploads (SMA-66), test-first.

A DOCX is a ZIP file holding XML parts. The TYPE is decided by the content, as for PDFs:
a ZIP with the Word parts inside. Word has no pages (they depend on the printer), so a
DOCX is cut into SECTIONS at its headings, and citations say "section 2".
"""

import json

import pytest
from sqlalchemy import select

from app.models import Chunk
from app.services.rag.extract import ExtractionError, extract_pages
from app.services.rag.retrieve import Hit
from app.services.study import sources_block
from app.services.uploads import DOCX_TYPE, MAX_UNZIPPED_BYTES, UploadRejected, check_upload
from tests.docx_maker import make_docx, make_zip, with_extra_file

ENTROPY = "Entropy always increases in an isolated system; it measures disorder."
HEAT = "Heat flows from a hot object to a cold one until both reach the same temperature."
LECTURE = make_docx(
    [
        "Thermodynamics lecture notes, week 3.",  # before the first heading: section 1
        "# Entropy",
        ENTROPY,
        "## Heat",
        HEAT,
        ["Quantity", "Unit"],
        ["Entropy", "J/K"],
    ]
)


# --- Checking the upload: by content, not by name ---------------------------------------------


def test_a_real_docx_is_accepted():
    checked = check_upload("Lecture.docx", LECTURE)

    assert checked.mime_type == DOCX_TYPE
    assert DOCX_TYPE == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.mark.parametrize(
    "name, data, why",
    [
        ("fake.docx", b"just some text with a .docx name", "not a real DOCX"),
        ("fake.docx", b"%PDF-1.7 a PDF renamed", "not a real DOCX"),
        ("slides.docx", make_zip({"ppt/presentation.xml": b"<p/>"}), "not a real DOCX"),
        ("broken.docx", b"PK\x03\x04 a zip that ends here", "not a real DOCX"),
        ("Lecture.pdf", LECTURE, "not a real PDF"),
        ("Lecture.txt", LECTURE, "not plain text"),
        ("Lecture.doc", LECTURE, "PDF, DOCX, TXT or MD"),  # old Word format: not supported
    ],
    ids=["text", "pdf", "other zip", "broken zip", "as pdf", "as txt", "old .doc"],
)
def test_a_disguised_file_gets_415(name, data, why):
    with pytest.raises(UploadRejected) as rejected:
        check_upload(name, data)

    assert rejected.value.status == 415
    assert why in rejected.value.message


def test_a_zip_bomb_is_refused_before_it_is_unpacked():
    # A few KB on disk that would unpack to more than the limit (zeros compress very well).
    bomb = with_extra_file(LECTURE, "word/media/huge.bin", b"\0" * (MAX_UNZIPPED_BYTES + 1))
    assert len(bomb) < 200_000

    with pytest.raises(UploadRejected) as rejected:
        check_upload("bomb.docx", bomb)

    assert rejected.value.status == 413
    assert "unpacked" in rejected.value.message


# --- Extracting the text: one "page" per section ----------------------------------------------


def test_each_heading_starts_a_new_numbered_section():
    extracted = extract_pages(LECTURE, DOCX_TYPE)

    assert extracted.page_count is None  # no pages
    assert [p.number for p in extracted.pages] == [1, 2, 3]
    intro, entropy, heat = (p.text for p in extracted.pages)
    assert intro == "Thermodynamics lecture notes, week 3."
    assert entropy.startswith("Entropy\n\n") and ENTROPY in entropy
    assert heat.startswith("Heat\n\n") and HEAT in heat


def test_tables_are_kept_as_rows():
    heat = extract_pages(LECTURE, DOCX_TYPE).pages[-1].text

    assert "Quantity | Unit\nEntropy | J/K" in heat


def test_a_document_without_headings_has_no_section_numbers():
    data = make_docx([ENTROPY, HEAT])

    pages = extract_pages(data, DOCX_TYPE).pages

    assert [p.number for p in pages] == [None]  # like a TXT file
    assert pages[0].text == f"{ENTROPY}\n\n{HEAT}"


def test_an_empty_document_is_rejected_with_a_clear_message():
    with pytest.raises(ExtractionError) as error:
        extract_pages(make_docx(["# Title only", "", "   "]), DOCX_TYPE)

    assert "No text found" in str(error.value)
    assert "scanned" not in str(error.value)  # that's the PDF message


def test_a_damaged_docx_is_a_clear_error():
    damaged = make_zip(
        {"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<not really word"}
    )

    with pytest.raises(ExtractionError, match="can't be read"):
        extract_pages(damaged, DOCX_TYPE)


# --- Citations say "section", never "page" ----------------------------------------------------


def test_the_ai_is_told_section_not_page():
    block = sources_block(
        [
            Hit("c1", "d1", "Lecture.docx", 2, ENTROPY, 0.9),
            Hit("c2", "d2", "Physics.pdf", 2, HEAT, 0.8),
        ]
    )

    assert 'document="Lecture.docx" section="2"' in block
    assert 'document="Physics.pdf" page="2"' in block


# --- Done when: the whole upload ---------------------------------------------------------------


def upload(client, name: str, data: bytes):
    return client.post("/api/documents", files={"file": (name, data, "application/octet-stream")})


def test_a_docx_upload_is_ready_and_its_chunks_know_their_section(client, db_session):
    response = upload(client, "Lecture.docx", LECTURE)

    assert response.status_code == 201, response.text
    document = json.loads(response.text.splitlines()[-1])["document"]
    assert (document["status"], document["mime_type"]) == ("ready", DOCX_TYPE)
    assert document["page_count"] is None
    chunks = db_session.scalars(select(Chunk).where(Chunk.document_id == document["id"])).all()
    assert {c.page for c in chunks} <= {1, 2, 3}
    assert any(ENTROPY in c.text for c in chunks)


def test_a_disguised_docx_upload_gets_415(client):
    response = upload(client, "fake.docx", b"plain text pretending")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_an_empty_docx_upload_ends_failed_with_the_reason(client):
    response = upload(client, "Empty.docx", make_docx([]))

    last = json.loads(response.text.splitlines()[-1])
    assert last["stage"] == "failed"
    assert "No text found" in last["error"]
