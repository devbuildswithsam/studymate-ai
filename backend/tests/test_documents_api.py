"""Uploading documents: only real PDF / DOCX / TXT / MD files up to 4 MB (guide 7.3, 9). SMA-44.

The type is decided by the file's CONTENT. The name and the browser's Content-Type header
are both chosen by whoever sends the file, so neither can be trusted.
"""

import json

import pytest

from app.main import app
from app.services.llm.embeddings import get_embedder
from app.services.llm.fake import FakeEmbeddingProvider
from app.services.uploads import safe_filename
from tests.pdf_maker import make_pdf

MB = 1024 * 1024
PDF = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"  # starts with the PDF magic bytes
NOTES = b"Entropy always increases in an isolated system, so heat flows from hot to cold."
BOM = "﻿".encode()  # the byte order mark Notepad puts at the start of UTF-8 files


def upload(client, name: str, data: bytes, content_type: str = "application/octet-stream"):
    return client.post("/api/documents", files={"file": (name, data, content_type)})


def events_of(response) -> list[dict]:
    """SMA-47: the upload answers with one JSON event per line (NDJSON)."""
    return [json.loads(line) for line in response.text.splitlines()]


def uploaded(client, name: str, data: bytes, **kwargs) -> dict:
    """Upload, and return the document from the last event (ready or failed)."""
    return events_of(upload(client, name, data, **kwargs))[-1]["document"]


def error_of(response) -> tuple[int, str, str]:
    error = response.json()["error"]
    return response.status_code, error["code"], error["message"]


def test_tests_never_reach_the_real_embedding_api(client):
    # conftest's client gives every test a fake embedder (CLAUDE.md: no real APIs in tests).
    make_embedder = app.dependency_overrides[get_embedder]()

    assert isinstance(make_embedder(), FakeEmbeddingProvider)


# --- Done when: valid files are accepted -------------------------------------------------


@pytest.mark.parametrize(
    "name, data, mime_type",
    [
        ("Physics.pdf", make_pdf([NOTES.decode()]), "application/pdf"),
        ("notes.txt", NOTES + " Δ S ≥ 0".encode(), "text/plain"),
        (
            "DBMS.md",
            b"# Normal forms\n\n- First normal form\n- Second normal form\n",
            "text/markdown",
        ),
        ("bom.txt", BOM + NOTES, "text/plain"),  # UTF-8 with a byte order mark
    ],
)
def test_a_valid_file_is_accepted_and_ingested(client, name, data, mime_type):
    response = upload(client, name, data)

    assert response.status_code == 201, response.text
    document = events_of(response)[-1]["document"]
    assert (document["filename"], document["mime_type"]) == (name, mime_type)
    assert (document["size_bytes"], document["status"]) == (len(data), "ready")


def test_exactly_4_mb_is_accepted(client):
    assert upload(client, "big.txt", b"a" * (4 * MB)).status_code == 201


# --- Done when: oversized or wrong-type files get clear 413 / 415 errors --------------------


def test_a_file_over_4_mb_gets_413(client):
    status, code, message = error_of(upload(client, "huge.txt", b"a" * (4 * MB + 1)))

    assert (status, code) == (413, "payload_too_large")
    assert "4 MB" in message


@pytest.mark.parametrize(
    "name, data, why",
    [
        ("slides.pptx", b"PK\x03\x04 a zip file", "PDF, DOCX, TXT or MD"),  # not an allowed type
        ("page.html", b"<html><script>alert(1)</script></html>", "PDF, DOCX, TXT or MD"),
        ("fake.pdf", b"just some text, not a PDF", "not a real PDF"),  # renamed text
        ("virus.pdf", b"MZ\x90\x00 a Windows program", "not a real PDF"),  # renamed program
        ("binary.txt", b"\x00\x01\x02\xff\xfe binary data", "not plain text"),
        ("nul.txt", b"valid UTF-8\x00\x00but with NUL bytes", "not plain text"),
        ("latin1.md", "café".encode("latin-1"), "not plain text"),  # not UTF-8
        ("hidden.txt", PDF, "is a PDF"),  # a PDF renamed .txt: wrong extension
        ("noextension", b"some text", "PDF, DOCX, TXT or MD"),
    ],
)
def test_a_wrong_or_disguised_type_gets_415(client, name, data, why):
    status, code, message = error_of(upload(client, name, data))

    assert (status, code) == (415, "unsupported_media_type")
    assert why in message


def test_the_browsers_content_type_header_is_ignored(client):
    # Claims to be a PDF, but the bytes are text: the bytes win.
    document = uploaded(client, "notes.txt", NOTES, content_type="application/pdf")

    assert document["mime_type"] == "text/plain"


def test_an_empty_file_is_refused(client):
    status, code, message = error_of(upload(client, "empty.txt", b""))

    assert (status, code) == (422, "validation_error")
    assert "empty" in message


@pytest.mark.parametrize(
    "sent, kept",
    [
        ("C:\\Users\\me\\Desktop\\Physics.pdf", "Physics.pdf"),  # a Windows path
        ("../../etc/passwd.txt", "passwd.txt"),  # path traversal: only the name is kept
        ("  spaced.md  ", "spaced.md"),
    ],
)
def test_only_the_files_own_name_is_kept(client, sent, kept):
    data = PDF if kept.endswith(".pdf") else NOTES

    assert uploaded(client, sent, data)["filename"] == kept


def test_a_very_long_name_is_shortened_but_keeps_its_extension(client):
    filename = uploaded(client, "x" * 300 + ".md", NOTES)["filename"]

    assert len(filename) <= 255 and filename.endswith(".md")


# --- List, get, delete -------------------------------------------------------------------


def test_my_documents_newest_first(client):
    upload(client, "first.txt", b"1")
    upload(client, "second.txt", b"2")

    assert [d["filename"] for d in client.get("/api/documents").json()] == [
        "second.txt",
        "first.txt",
    ]


def test_get_and_delete_one_document(client):
    document_id = uploaded(client, "notes.txt", NOTES)["id"]

    assert client.get(f"/api/documents/{document_id}").json()["filename"] == "notes.txt"
    assert client.delete(f"/api/documents/{document_id}").status_code == 204
    assert client.get(f"/api/documents/{document_id}").status_code == 404
    assert client.get("/api/documents").json() == []


# --- The file name, checked directly ----------------------------------------------------
# The upload library already strips some paths before our code sees them; safe_filename is
# the second line of defence, so it is tested on its own too.


@pytest.mark.parametrize(
    "sent, kept",
    [
        (r"C:\Users\me\Physics.pdf", "Physics.pdf"),  # r"...": backslashes stay as typed
        (r"..\..\Windows\evil.txt", "evil.txt"),
        ("../../etc/passwd.txt", "passwd.txt"),
        ("folder/", "unnamed"),
        ("", "unnamed"),
    ],
)
def test_safe_filename(sent, kept):
    assert safe_filename(sent) == kept


# --- SMA-47: the upload streams the ingest progress ------------------------------------------


def test_the_upload_streams_each_step_then_the_ready_document(client):
    pages = [  # different text on each page: a line on every page is a header (SMA-45)
        NOTES.decode(),
        "Work is the force on an object times the distance it moves, in joules.",
        "Power is the rate of doing work, measured in watts.",
    ]
    response = upload(client, "Physics.pdf", make_pdf(pages))

    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = events_of(response)
    assert [e["stage"] for e in events[:4]] == ["extracting"] * 4  # start, then pages 1-3
    assert [(e["done"], e["total"]) for e in events[1:4]] == [(1, 3), (2, 3), (3, 3)]
    assert events[-1]["stage"] == "ready"
    assert (events[-1]["document"]["status"], events[-1]["document"]["page_count"]) == ("ready", 3)


def test_a_scanned_pdf_upload_ends_failed_with_the_reason(client):
    events = events_of(upload(client, "Scan.pdf", make_pdf([None, None])))

    assert events[-1]["stage"] == "failed"
    assert "No text found" in events[-1]["error"]
    document = events[-1]["document"]
    assert (document["status"], document["can_retry"]) == ("failed", False)  # upload again


def test_an_embedding_failure_during_upload_can_be_retried(client):
    app.dependency_overrides[get_embedder] = lambda: (lambda: FakeEmbeddingProvider(fail_on_call=1))

    document = uploaded(client, "notes.txt", NOTES)

    assert (document["status"], document["can_retry"]) == ("failed", True)
    app.dependency_overrides[get_embedder] = lambda: (lambda: FakeEmbeddingProvider())
    retried = client.post(f"/api/documents/{document['id']}/retry").json()
    assert retried["status"] == "ready"


def test_the_list_shows_the_final_status(client):
    uploaded(client, "notes.txt", NOTES)

    assert [d["status"] for d in client.get("/api/documents").json()] == ["ready"]


def test_a_pdf_with_only_headers_and_page_numbers_ends_failed(client):
    """SMA-69: enough letters to pass extraction, but cleaning removes the repeated header
    and the page numbers, so nothing is left to search."""
    pages = [f"Physics Notes\n{n}" for n in range(1, 4)]

    last = events_of(upload(client, "Headers.pdf", make_pdf(pages)))[-1]

    assert last["stage"] == "failed"
    assert "No text found" in last["error"]
