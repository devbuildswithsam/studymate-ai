"""Write small, real PDFs for tests (SMA-45), so no binary files live in the repo.

make_pdf(["page 1 text", None, "page 3 text"]): one page per item. A string becomes text
lines on the page (one PDF text line per line); None makes an IMAGE-ONLY page (a picture
and no text at all), like a scanned document.

A PDF is a list of numbered objects (catalog, pages, fonts, page contents) plus a table
of where each object starts (the "xref"). Text is drawn by a little program in each
page's content stream: BT ... (Hello) Tj ... ET.
"""


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _text_program(text: str) -> bytes:
    lines = ["BT", "/F1 11 Tf", "14 TL", "72 740 Td"]
    for line in text.split("\n"):
        lines.append(f"({_escape(line)}) Tj T*")  # draw the line, then move to the next
    lines.append("ET")
    return "\n".join(lines).encode("latin-1")


IMAGE_PROGRAM = b"q 200 0 0 200 72 500 cm /Im1 Do Q"  # draw image Im1, 200x200 points


def make_pdf(pages: list[str | None]) -> bytes:
    objects: list[bytes] = []  # object n is objects[n - 1]

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")  # filled in at the end
    pages_obj = add(b"")
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    image = add(
        b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray"
        b" /BitsPerComponent 8 /Length 1 >>\nstream\n\x80\nendstream"
    )
    kids = []
    for text in pages:
        program = IMAGE_PROGRAM if text is None else _text_program(text)
        content = add(b"<< /Length %d >>\nstream\n" % len(program) + program + b"\nendstream")
        kids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] /Contents %d 0 R"
                b" /Resources << /Font << /F1 %d 0 R >> /XObject << /Im1 %d 0 R >> >> >>"
                % (pages_obj, content, font, image)
            )
        )
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj
    objects[pages_obj - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )

    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        catalog,
        xref,
    )
    return bytes(out)
