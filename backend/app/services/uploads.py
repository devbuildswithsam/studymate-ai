"""Checking an uploaded file before we accept it (guide 7.3 step 1, guide 9). SMA-44.

The file's name and the browser's Content-Type header are chosen by whoever sends the file,
so the TYPE is decided by the bytes:
- a PDF must start with the PDF "magic bytes" %PDF-
- TXT / MD must be UTF-8 text with no NUL bytes (binary files nearly always have some)
The name's extension must agree with the content: a PDF renamed .txt is refused too.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

MAX_UPLOAD_BYTES = 4 * 1024 * 1024  # 4 MB (guide: Vercel's 4.5 MB body limit, minus overhead)
MAX_FILENAME_CHARS = 255
PDF_MAGIC = b"%PDF-"
TEXT_TYPES = {".txt": "text/plain", ".md": "text/markdown"}


class UploadRejected(Exception):
    """The file can't be accepted. status: 413 (too big), 415 (wrong type), 422 (empty)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class CheckedUpload:
    filename: str  # safe to show; never used as a path
    mime_type: str
    size_bytes: int


def check_upload(filename: str, data: bytes) -> CheckedUpload:
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejected(413, "The file is larger than 4 MB. Try a smaller file.")
    if not data:
        raise UploadRejected(422, "The file is empty.")
    name = safe_filename(filename)
    return CheckedUpload(name, content_type(name, data), len(data))


def content_type(name: str, data: bytes) -> str:
    extension = PurePosixPath(name).suffix.lower()
    is_pdf = data.startswith(PDF_MAGIC)
    if extension == ".pdf":
        if not is_pdf:
            raise UploadRejected(415, f"{name} is not a real PDF (its content doesn't match).")
        return "application/pdf"
    if extension in TEXT_TYPES:
        if is_pdf:
            raise UploadRejected(415, f"{name} is a PDF: rename it to .pdf.")
        if not is_utf8_text(data):
            raise UploadRejected(415, f"{name} is not plain text (UTF-8).")
        return TEXT_TYPES[extension]
    raise UploadRejected(415, "Only PDF, TXT or MD files can be uploaded.")


def is_utf8_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")  # a BOM (Notepad) is fine: "utf-8" keeps it as \ufeff
    except UnicodeDecodeError:
        return False
    return True


def safe_filename(filename: str) -> str:
    """Only the file's own name: no folders (C:\\..., ../..), short enough to store."""
    name = re.split(r"[\\/]", filename)[-1].strip()
    if len(name) > MAX_FILENAME_CHARS:
        extension = PurePosixPath(name).suffix[:10]
        name = name[: MAX_FILENAME_CHARS - len(extension)] + extension
    return name or "unnamed"
