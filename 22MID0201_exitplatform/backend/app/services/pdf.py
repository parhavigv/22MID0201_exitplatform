"""A minimal single-page PDF writer.

Written by hand rather than with reportlab or fpdf. A one-page text document is
a small, well-specified format, and the deployment this runs in cannot take new
dependencies. `scripts/make_sample_documents.py` proved the approach on the
demo fixtures; this is the same builder, moved here so the request path can use
it too.

Callers describe a page as (style, text) pairs and never touch PDF syntax:

    build_pdf([("h1", "TITLE"), ("", ""), ("b", "Some body text")])

Styles: 'h1' document title, 'h2' section heading, 'b' body, '' blank line.
"""

from __future__ import annotations

PAGE_W, PAGE_H = 595, 842  # A4, in PDF points
MARGIN_X, TOP_Y = 56, 786
LEADING = 15.5

Line = tuple[str, str]


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: list[Line]) -> bytes:
    out = ["BT", f"1 0 0 1 {MARGIN_X} {TOP_Y} Tm", f"{LEADING} TL"]
    for style, text in lines:
        if style == "h1":
            out.append("/F2 16 Tf")
        elif style == "h2":
            out.append("/F2 11 Tf")
        else:
            out.append("/F1 10.5 Tf")
        out.append(f"({_escape(text)}) Tj" if text else "() Tj")
        out.append("T*")
    out.append("ET")
    # Helvetica's built-in encoding is Latin-1; anything outside it (an em dash
    # pasted into a name, say) becomes '?' rather than corrupting the stream.
    return "\n".join(out).encode("latin-1", "replace")


def build_pdf(lines: list[Line]) -> bytes:
    """Assemble a single-page PDF.

    The xref table stores each object's exact byte offset, so objects are
    appended one at a time and their start positions recorded as we go — a
    wrong offset makes the file unopenable in most readers.
    """
    stream = _content_stream(lines)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
            + f"{PAGE_W} {PAGE_H}".encode()
            + b"] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n".encode()
        + b"%%EOF\n"
    )
    return bytes(pdf)


def rule(width: int = 78) -> list[Line]:
    return [("b", "_" * width)]


def field(label: str, value: object, pad: int = 22) -> Line:
    """A left-aligned label with its value in a second column."""
    return ("b", f"{label.ljust(pad)}{value if value not in (None, '') else '-'}")
