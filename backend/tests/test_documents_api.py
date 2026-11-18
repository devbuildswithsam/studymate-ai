"""Uploading documents: only real PDF / TXT / MD files up to 4 MB (guide 7.3, 9). SMA-44.

The type is decided by the file's CONTENT. The name and the browser's Content-Type header
are both chosen by whoever sends the file, so neither can be trusted.
"""

import pytest

from app.services.uploads import safe_filename

MB = 1024 * 1024
PDF = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"  # starts with the PDF magic bytes


def upload(client, name: str, data: bytes, content_type: str = "application/octet-stream"):
    return client.post("/api/documents", files={"file": (name, data, content_type)})


def error_of(response) -> tuple[int, str, str]:
    error = response.json()["error"]
    return response.status_code, error["code"], error["message"]


# --- Done when: valid files are accepted -------------------------------------------------


@pytest.mark.parametrize(
    "name, data, mime_type",
    [
        ("Physics.pdf", PDF, "application/pdf"),
        ("notes.txt", "Entropy always increases. Δ S ≥ 0".encode(), "text/plain"),
        ("DBMS.md", b"# Normal forms\n\n- 1NF\n- 2NF\n", "text/markdown"),
        ("bom.txt", "\ufeffText saved by Notepad".encode(), "text/plain"),  # UTF-8 with BOM
    ],
)
def test_a_valid_file_is_accepted_and_waits_to_be_processed(client, name, data, mime_type):
    response = upload(client, name, data)

    assert response.status_code == 201, response.text
    document = response.json()
    assert (document["filename"], document["mime_type"]) == (name, mime_type)
    assert (document["size_bytes"], document["status"]) == (len(data), "processing")


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
        ("slides.pptx", b"PK\x03\x04 a zip file", "PDF, TXT or MD"),  # not an allowed type
        ("page.html", b"<html><script>alert(1)</script></html>", "PDF, TXT or MD"),
        ("fake.pdf", b"just some text, not a PDF", "not a real PDF"),  # renamed text
        ("virus.pdf", b"MZ\x90\x00 a Windows program", "not a real PDF"),  # renamed program
        ("binary.txt", b"\x00\x01\x02\xff\xfe binary data", "not plain text"),
        ("nul.txt", b"valid UTF-8\x00\x00but with NUL bytes", "not plain text"),
        ("latin1.md", "café".encode("latin-1"), "not plain text"),  # not UTF-8
        ("hidden.txt", PDF, "is a PDF"),  # a PDF renamed .txt: wrong extension
        ("noextension", b"some text", "PDF, TXT or MD"),
    ],
)
def test_a_wrong_or_disguised_type_gets_415(client, name, data, why):
    status, code, message = error_of(upload(client, name, data))

    assert (status, code) == (415, "unsupported_media_type")
    assert why in message


def test_the_browsers_content_type_header_is_ignored(client):
    # Claims to be a PDF, but the bytes are text: the bytes win.
    response = upload(client, "notes.txt", b"plain text", content_type="application/pdf")

    assert response.json()["mime_type"] == "text/plain"


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
    data = PDF if kept.endswith(".pdf") else b"text"

    assert upload(client, sent, data).json()["filename"] == kept


def test_a_very_long_name_is_shortened_but_keeps_its_extension(client):
    filename = upload(client, "x" * 300 + ".md", b"text").json()["filename"]

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
    document_id = upload(client, "notes.txt", b"text").json()["id"]

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
