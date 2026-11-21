"""Write small, real DOCX files for tests (SMA-66), so no binary files live in the repo.

make_docx(["# Heading", "A paragraph.", ["cell", "cell"], ...]):
- a string starting with "# " / "## " is a Word heading (level 1 / 2)
- any other string is a normal paragraph
- a list is one table row (one string per cell)
"""

import io
import zipfile

import docx


def make_docx(blocks: list[str | list[str]]) -> bytes:
    document = docx.Document()
    table = None
    for block in blocks:
        if isinstance(block, list):
            if table is None:  # consecutive rows make one table
                table = document.add_table(rows=0, cols=len(block))
            cells = table.add_row().cells
            for cell, text in zip(cells, block, strict=True):
                cell.text = text
            continue
        table = None
        if block.startswith("## "):
            document.add_heading(block[3:], level=2)
        elif block.startswith("# "):
            document.add_heading(block[2:], level=1)
        else:
            document.add_paragraph(block)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def make_zip(files: dict[str, bytes]) -> bytes:
    """Any ZIP file, e.g. one that is NOT a Word document, or a "zip bomb"."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return out.getvalue()


def with_extra_file(data: bytes, name: str, content: bytes) -> bytes:
    """A real DOCX with one more file packed inside."""
    source = zipfile.ZipFile(io.BytesIO(data))
    files = {info.filename: source.read(info) for info in source.infolist()}
    return make_zip({**files, name: content})
