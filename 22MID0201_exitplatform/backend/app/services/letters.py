"""Generate the documents the company issues, from the exit record.

Why this exists
---------------
Issuing a relieving letter meant HR already having a PDF: write it in Word,
export it, upload it. If they did not have one, the employee simply never got
their letter — and the case could still be closed around the gap, which is how
one case here ended up permanently missing two Finance documents.

Every fact these letters state is already in the database: the name, the
dates, the designation, the settlement arithmetic. So the platform can write
them, and HR's job becomes reviewing rather than authoring.

Not a replacement for HR's own stationery. `upload_document` still accepts a
file, and a company that wants its letterhead and its own wording uses that.
This is the floor, not the ceiling: it guarantees the employee receives
something accurate rather than nothing.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.pdf import Line, build_pdf, field, rule

# The document types this module can write. Anything outside it must be
# uploaded — there is no generic "make me a PDF" path, because a letter whose
# wording nobody has specified is worse than an honest blank.
GENERATABLE = {
    "RELIEVING_LETTER",
    "EXPERIENCE_LETTER",
    "NO_DUES_FINANCE",
    "FINAL_SETTLEMENT_STATEMENT",
}


def _long(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d %B %Y")
    except ValueError:
        return str(value)


def _money(value: Any) -> str:
    return "-" if value is None else f"{float(value):,.2f}"


def _header(title: str, employee: dict[str, Any], case: dict[str, Any]) -> list[Line]:
    return [
        ("h1", title),
        ("", ""),
        *rule(),
        ("", ""),
        field("Employee", employee["full_name"]),
        field("Employee code", employee["emp_code"]),
        field("Designation", employee["designation"]),
        field("Department", employee["department"]),
        field("Date of joining", _long(employee.get("date_of_joining"))),
        field("Last working day", _long(case["last_working_day"])),
        ("", ""),
    ]


def _footer(case_id: str, issued_by: str) -> list[Line]:
    return [
        ("", ""),
        *rule(),
        ("", ""),
        field("Issued by", issued_by),
        field("Issue date", _long(date.today().isoformat())),
        field("Case reference", case_id),
        ("", ""),
        ("b", "Generated from the exit record. A signed copy on company"),
        ("b", "letterhead may be requested from Human Resources."),
    ]


def _relieving(employee, case, **_) -> list[Line]:
    return [
        *_header("RELIEVING LETTER", employee, case),
        ("h2", "TO WHOMSOEVER IT MAY CONCERN"),
        ("", ""),
        ("b", f"This is to confirm that {employee['full_name']} has been relieved"),
        ("b", "from the services of the company with effect from the close of"),
        ("b", f"business on {_long(case['last_working_day'])}."),
        ("", ""),
        ("b", "All exit formalities recorded on the exit platform have been"),
        ("b", "completed, including knowledge transfer, IT clearance, finance"),
        ("b", "clearance and the return of company property."),
        ("", ""),
        ("b", "We confirm that no dues remain outstanding on either side as at"),
        ("b", "the date of this letter."),
    ]


def _experience(employee, case, **_) -> list[Line]:
    return [
        *_header("EXPERIENCE CERTIFICATE", employee, case),
        ("h2", "TO WHOMSOEVER IT MAY CONCERN"),
        ("", ""),
        ("b", f"This is to certify that {employee['full_name']} was employed with"),
        ("b", f"the company as {employee['designation']} in the"),
        ("b", f"{employee['department']} department from"),
        (
            "b",
            f"{_long(employee.get('date_of_joining'))} to "
            f"{_long(case['last_working_day'])}.",
        ),
        ("", ""),
        ("b", "During this period their conduct and performance were found to be"),
        ("b", "satisfactory. We wish them success in their future endeavours."),
    ]


def _no_dues(employee, case, *, settlement: list[dict[str, Any]], **_) -> list[Line]:
    outstanding = [
        s
        for s in settlement
        if s["kind"] == "deduction"
        and s["status"] == "confirmed"
        and s.get("amount")
    ]
    lines: list[Line] = [
        *_header("NO-DUES CERTIFICATE", employee, case),
        ("h2", "FINANCE CLEARANCE"),
        ("", ""),
    ]
    if outstanding:
        # An honest no-dues names what is being recovered. Declaring "no dues"
        # while deducting from the settlement would contradict the statement
        # issued alongside it.
        lines += [
            ("b", "The following amounts are recoverable and will be adjusted"),
            ("b", "against the full and final settlement:"),
            ("", ""),
        ]
        lines += [field(s["label"], _money(s["amount"])) for s in outstanding]
        lines += [
            ("", ""),
            ("b", "Subject to that adjustment, Finance confirms no further dues"),
            ("b", "are outstanding from the employee."),
        ]
    else:
        lines += [
            ("b", "Finance confirms that no dues are outstanding from the"),
            ("b", "employee as at the date of this certificate. Advances,"),
            ("b", "reimbursements and company-funded obligations have all been"),
            ("b", "settled or closed."),
        ]
    return lines


def _settlement(employee, case, *, settlement: list[dict[str, Any]], **_) -> list[Line]:
    earnings = [s for s in settlement if s["kind"] == "earning"]
    deductions = [s for s in settlement if s["kind"] == "deduction"]

    def total(rows: list[dict[str, Any]]) -> float:
        return sum(
            float(r["amount"])
            for r in rows
            if r["status"] == "confirmed" and r.get("amount") is not None
        )

    def block(title: str, rows: list[dict[str, Any]]) -> list[Line]:
        out: list[Line] = [("h2", title), ("", "")]
        for r in rows:
            # A pending line is shown as pending, never as zero. A statement
            # that silently drops an unconfirmed amount reads as final when it
            # is not.
            shown = (
                _money(r["amount"]) if r["status"] == "confirmed" else "to be confirmed"
            )
            out.append(field(r["label"], shown, pad=40))
        out.append(("", ""))
        return out

    net = total(earnings) - total(deductions)
    unconfirmed = [s for s in settlement if s["status"] == "pending"]

    lines: list[Line] = [
        *_header("FULL AND FINAL SETTLEMENT STATEMENT", employee, case),
        *block("EARNINGS", earnings),
        *block("DEDUCTIONS", deductions),
        *rule(),
        field("NET PAYABLE", _money(net), pad=40),
        *rule(),
    ]
    if unconfirmed:
        lines += [
            ("", ""),
            ("b", f"{len(unconfirmed)} line(s) remain to be confirmed by Finance."),
            ("b", "The net figure above covers confirmed lines only and will"),
            ("b", "change when the remainder are settled."),
        ]
    return lines


_WRITERS = {
    "RELIEVING_LETTER": _relieving,
    "EXPERIENCE_LETTER": _experience,
    "NO_DUES_FINANCE": _no_dues,
    "FINAL_SETTLEMENT_STATEMENT": _settlement,
}


def generate(
    doc_type_code: str,
    *,
    employee: dict[str, Any],
    case: dict[str, Any],
    settlement: list[dict[str, Any]],
    issued_by: str,
) -> bytes:
    """Build the PDF for `doc_type_code`. Raises KeyError if not generatable."""
    writer = _WRITERS[doc_type_code]
    body = writer(employee, case, settlement=settlement)
    return build_pdf([*body, *_footer(case["id"], issued_by)])
