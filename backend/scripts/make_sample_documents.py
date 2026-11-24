"""Generate blank-but-realistic PDFs for every document the platform accepts.

Why this exists
---------------
Demoing the upload flow needs actual files on disk, and the upload endpoint
only accepts PDF, PNG or JPEG. These are deliberately generic — no employee
name, no dates that can go stale — so the same file can be submitted for any
employee without looking wrong.

The PDFs are written by hand rather than with a library. A one-page text
document is a small, well-specified format, and the alternative was adding a
dependency purely to produce demo fixtures.

NDA_ACKNOWLEDGEMENT is missing on purpose: it is filled in inside the app
(migration 0007, inline documents) and has no file to upload.

Usage
-----
    cd backend
    .venv/Scripts/python.exe scripts/make_sample_documents.py

Files land on the Desktop in "Exit Platform Sample Documents". Pass a path to
put them somewhere else.
"""

from __future__ import annotations

import argparse
from pathlib import Path

PAGE_W, PAGE_H = 595, 842          # A4 in PDF points
MARGIN_X, TOP_Y = 56, 786
LEADING = 15.5


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: list[tuple[str, str]]) -> bytes:
    """Build the page's drawing commands from (style, text) pairs.

    Styles: 'h1' document title, 'h2' section heading, 'b' body, '' blank line.
    """
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
    return "\n".join(out).encode("latin-1", "replace")


def build_pdf(lines: list[tuple[str, str]]) -> bytes:
    """Assemble a single-page PDF. Offsets in the xref table must be exact, so
    each object is appended and its start position recorded as we go."""
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


def _rule() -> list[tuple[str, str]]:
    return [("b", "_" * 78)]


DOCUMENTS: dict[str, list[tuple[str, str]]] = {
    "Resignation Letter": [
        ("h1", "LETTER OF RESIGNATION"), ("", ""), *_rule(), ("", ""),
        ("b", "To:      The Reporting Manager"), ("b", "Copy:    Human Resources"), ("", ""),
        ("h2", "Notice of Resignation"), ("", ""),
        ("b", "I am writing to formally resign from my position with the company."),
        ("b", "This letter serves as written notice in line with the Notice Period"),
        ("b", "Policy, and I understand the notice period begins on the calendar day"),
        ("b", "following the date this letter is received and acknowledged."), ("", ""),
        ("b", "I will work with my manager to agree a handover plan and to document"),
        ("b", "the systems, processes and open work I currently own, so that my"),
        ("b", "successor can take them on without disruption."), ("", ""),
        ("b", "I confirm that I will return all company assets and will continue to"),
        ("b", "honour my confidentiality obligations after my last working day."), ("", ""),
        ("h2", "Details"), ("", ""),
        ("b", "Intended last working day ......................................."),
        ("b", "Date of this letter .............................................."),
        ("b", "Employee signature .............................................."), ("", ""), ("", ""),
        ("b", "Thank you for the opportunity and the support during my time here."),
    ],
    "Knowledge Transfer Document": [
        ("h1", "KNOWLEDGE TRANSFER DOCUMENT"), ("", ""), *_rule(), ("", ""),
        ("b", "Prepared by ..................  Successor .................."),
        ("b", "Reviewed by manager ..........  Date ......................."), ("", ""),
        ("h2", "1. Systems and Services Owned"), ("", ""),
        ("b", "Name, purpose, where it runs, and how it is deployed."),
        ("b", "  a) ........................................................."),
        ("b", "  b) ........................................................."),
        ("b", "  c) ........................................................."), ("", ""),
        ("h2", "2. Access and Credentials"), ("", ""),
        ("b", "Accounts, vaults and permissions involved. Credentials are handed"),
        ("b", "over through the approved secrets manager and are never written"),
        ("b", "into this document."),
        ("b", "  ............................................................"), ("", ""),
        ("h2", "3. Runbooks and Known Failure Modes"), ("", ""),
        ("b", "Routine operation, and recovery steps when it breaks."),
        ("b", "  ............................................................"), ("", ""),
        ("h2", "4. Open Work in Flight"), ("", ""),
        ("b", "Item, current state, and what 'done' looks like."),
        ("b", "  ............................................................"), ("", ""),
        ("h2", "5. Key Contacts"), ("", ""),
        ("b", "Internal stakeholders and external vendors, with context."),
        ("b", "  ............................................................"), ("", ""),
        ("h2", "6. Institutional Context"), ("", ""),
        ("b", "Decisions taken, alternatives rejected, and why."),
        ("b", "  ............................................................"),
    ],
    "Asset Return Form": [
        ("h1", "ASSET RETURN FORM"), ("", ""), *_rule(), ("", ""),
        ("b", "Employee .....................  Department ..................."),
        ("b", "Return date ..................  Received by .................."), ("", ""),
        ("h2", "Items Returned"), ("", ""),
        ("b", "Item                          Identifier        Condition"),
        ("b", "Laptop                        ..............    ............"),
        ("b", "Charger and power adapter     ..............    ............"),
        ("b", "Monitor                       ..............    ............"),
        ("b", "Keyboard and mouse            ..............    ............"),
        ("b", "Mobile phone / SIM            ..............    ............"),
        ("b", "Headset                       ..............    ............"),
        ("b", "ID and building access card   ..............    ............"),
        ("b", "Locker key                    ..............    ............"),
        ("b", "Corporate credit card         ..............    ............"),
        ("b", "Other ......................  ..............    ............"), ("", ""),
        ("h2", "Condition Assessment"), ("", ""),
        ("b", "Fair wear and tear is expected and is not recovered from the"),
        ("b", "employee. Damage beyond fair wear, or non-return, is recovered"),
        ("b", "through the full-and-final settlement."), ("", ""),
        ("b", "Notes ......................................................."), ("", ""),
        ("b", "IT / Admin signature .........  Employee signature ..........."),
    ],
    "Finance No-Dues Certificate": [
        ("h1", "FINANCE NO-DUES CERTIFICATE"), ("", ""), *_rule(), ("", ""),
        ("b", "Employee .....................  Department ..................."),
        ("b", "Last working day .............  Issued on ...................."), ("", ""),
        ("h2", "Clearance Checklist"), ("", ""),
        ("b", "[  ]  Salary advances recovered or scheduled"),
        ("b", "[  ]  Travel and expense claims submitted before the cut-off"),
        ("b", "[  ]  Corporate credit card balance cleared and card surrendered"),
        ("b", "[  ]  Company loans settled or a repayment schedule agreed"),
        ("b", "[  ]  Petty cash and floats returned"), ("", ""),
        ("h2", "Outstanding Amounts"), ("", ""),
        ("b", "Description                              Amount"),
        ("b", "......................................   ..........."),
        ("b", "......................................   ..........."),
        ("b", "Total to recover from F&F .............   ..........."), ("", ""),
        ("h2", "Certification"), ("", ""),
        ("b", "Finance confirms that, subject to the amounts listed above, the"),
        ("b", "employee has no outstanding dues to the company and the full-and-"),
        ("b", "final settlement may be released."), ("", ""),
        ("b", "Finance signature ............  Name ........................."),
    ],
    "Full and Final Settlement Statement": [
        ("h1", "FULL AND FINAL SETTLEMENT STATEMENT"), ("", ""), *_rule(), ("", ""),
        ("b", "Employee .....................  Last working day ............."),
        ("b", "Statement date ...............  Payable by ..................."), ("", ""),
        ("h2", "Earnings"), ("", ""),
        ("b", "Salary up to last working day .....................  ........."),
        ("b", "Leave encashment ..................................  ........."),
        ("b", "Gratuity (if eligible) ............................  ........."),
        ("b", "Reimbursements approved ...........................  ........."),
        ("b", "Bonus or variable pay due .........................  ........."),
        ("b", "Gross earnings ....................................  ........."), ("", ""),
        ("h2", "Deductions"), ("", ""),
        ("b", "Notice period shortfall ...........................  ........."),
        ("b", "Salary advances ...................................  ........."),
        ("b", "Unreturned or damaged assets ......................  ........."),
        ("b", "Statutory deductions and tax ......................  ........."),
        ("b", "Total deductions ..................................  ........."), ("", ""),
        ("h2", "Net Settlement"), ("", ""),
        ("b", "Net amount payable ................................  ........."), ("", ""),
        ("b", "Released only after IT, Finance and Admin clearance is complete."), ("", ""),
        ("b", "Finance signature ............  Employee acknowledgement ....."),
    ],
    "Relieving Letter": [
        ("h1", "RELIEVING LETTER"), ("", ""), *_rule(), ("", ""),
        ("b", "Date ........................................................."), ("", ""),
        ("h2", "To Whom It May Concern"), ("", ""),
        ("b", "This is to certify that the employee named below was employed with"),
        ("b", "the company and has been formally relieved of all duties with"),
        ("b", "effect from the close of business on the last working day stated."), ("", ""),
        ("b", "Employee name ................................................"),
        ("b", "Employee code ................................................"),
        ("b", "Designation ..................................................."),
        ("b", "Department ...................................................."),
        ("b", "Date of joining ..............................................."),
        ("b", "Last working day .............................................."), ("", ""),
        ("h2", "Clearance"), ("", ""),
        ("b", "All company assets have been returned and IT, Finance and Admin"),
        ("b", "clearances are complete. The full-and-final settlement has been"),
        ("b", "processed. No dues remain outstanding on either side."), ("", ""),
        ("b", "We thank the employee for their service and wish them well."), ("", ""),
        ("b", "Authorised signatory ............  Human Resources"),
    ],
    "Experience Letter": [
        ("h1", "EXPERIENCE CERTIFICATE"), ("", ""), *_rule(), ("", ""),
        ("b", "Date ........................................................."), ("", ""),
        ("h2", "To Whom It May Concern"), ("", ""),
        ("b", "This is to certify that the person named below was employed with"),
        ("b", "the company for the period stated, in the capacity described."), ("", ""),
        ("b", "Employee name ................................................"),
        ("b", "Designation at exit ..........................................."),
        ("b", "Department ...................................................."),
        ("b", "Period of employment ..........  to  ........................."), ("", ""),
        ("b", "During this period the employee was associated with the team and"),
        ("b", "contributed to the responsibilities of the role described above."), ("", ""),
        ("b", "This certificate is issued on request and states dates, final"),
        ("b", "designation and department only. It carries no assessment of"),
        ("b", "performance or conduct."), ("", ""),
        ("b", "Authorised signatory ............  Human Resources"),
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "out_dir", nargs="?",
        default=str(Path.home() / "Desktop" / "Exit Platform Sample Documents"),
        help="Where to write the PDFs.",
    )
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    for name, lines in DOCUMENTS.items():
        path = out / f"{name}.pdf"
        path.write_bytes(build_pdf(lines))
        print(f"  {path.name:<42} {path.stat().st_size:>6,} bytes")

    print(f"\n{len(DOCUMENTS)} file(s) written to:\n  {out}")
    print("\nNDA Acknowledgement is not here — it is filled in inside the app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
