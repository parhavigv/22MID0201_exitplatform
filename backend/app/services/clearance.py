"""Build the itemised clearance lists for a case.

What goes on each list depends on the person. An engineer holds repository and
cloud access an account executive never does; a remote worker has a home-office
monitor to send back. So the sets below are assembled from department and
designation rather than being one fixed list everybody gets — a checklist full
of rows marked "not applicable" trains people to tick without reading.

This is a starting point, not an inventory. The platform has no connection to a
real asset register or identity provider, so these are the items someone in this
role *probably* holds, and IT confirms or corrects them. The UI says as much;
pretending otherwise would be worse than the single checkbox this replaces.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any

from app.deps import service_db

# --- assets -----------------------------------------------------------------

_BASE_ASSETS: list[tuple[str, str]] = [
    ("Laptop", "hardware"),
    ("Laptop charger", "hardware"),
    ("Employee ID card", "access"),
    ("Building access card", "access"),
]

_EXTRA_ASSETS: dict[str, list[tuple[str, str]]] = {
    "Engineering": [("External monitor", "hardware"), ("Headset", "hardware")],
    "DevOps": [("External monitor", "hardware"), ("Hardware MFA token", "access")],
    "Quality Assurance": [("Test device", "hardware"), ("Headset", "hardware")],
    "Data & Analytics": [("External monitor", "hardware")],
    "Sales": [("Mobile phone", "mobile"), ("SIM card", "mobile")],
    "Finance": [("Corporate credit card", "other")],
}

# --- access -----------------------------------------------------------------
# (system, category, elevated)

_BASE_ACCESS: list[tuple[str, str, bool]] = [
    ("Single sign-on (identity provider)", "identity", False),
    ("Email and calendar", "mail", False),
    ("Chat — Slack / Teams", "collaboration", False),
    ("Wiki and document store", "collaboration", False),
    ("Ticketing system", "collaboration", False),
    ("VPN certificate", "physical", False),
    ("Building access", "physical", False),
]

_EXTRA_ACCESS: dict[str, list[tuple[str, str, bool]]] = {
    "Engineering": [
        ("Source control", "engineering", False),
        ("CI / build system", "engineering", False),
        ("Cloud console", "engineering", True),
        ("Production database", "engineering", True),
    ],
    "DevOps": [
        ("Source control", "engineering", False),
        ("Cloud console — administrator", "engineering", True),
        ("Secrets manager", "engineering", True),
        ("Production database", "engineering", True),
        ("On-call paging", "engineering", False),
    ],
    "Quality Assurance": [
        ("Source control", "engineering", False),
        ("Test environments", "engineering", False),
    ],
    "Data & Analytics": [
        ("Data warehouse", "engineering", True),
        ("BI / reporting tool", "engineering", False),
    ],
    "Sales": [("CRM", "collaboration", False)],
    "Finance": [("Payroll system", "collaboration", True), ("ERP", "collaboration", True)],
}

# Anyone senior enough to be an owner somewhere. Matched on designation.
_SENIOR_MARKERS = ("lead", "principal", "architect", "manager", "head", "staff", "senior")
_SENIOR_ACCESS: list[tuple[str, str, bool]] = [
    ("Administrative rights on owned systems", "identity", True),
]

# --- settlement -------------------------------------------------------------
# (kind, label)

_SETTLEMENT_LINES: list[tuple[str, str]] = [
    ("earning", "Salary up to last working day"),
    ("earning", "Leave encashment"),
    ("earning", "Gratuity (if eligible)"),
    ("earning", "Approved reimbursements"),
    ("earning", "Bonus or variable pay due"),
    ("deduction", "Notice period shortfall"),
    ("deduction", "Salary advances"),
    ("deduction", "Unreturned or damaged assets"),
    ("deduction", "Statutory deductions and tax"),
]


def _assets_for(department: str) -> list[tuple[str, str]]:
    return _BASE_ASSETS + _EXTRA_ASSETS.get(department, [])


def _access_for(department: str, designation: str) -> list[tuple[str, str, bool]]:
    rows = _BASE_ACCESS + _EXTRA_ACCESS.get(department, [])
    if any(m in (designation or "").lower() for m in _SENIOR_MARKERS):
        rows = rows + _SENIOR_ACCESS
    return rows


def compute_settlement(
    profile: dict[str, Any] | None,
    case: dict[str, Any],
) -> dict[str, tuple[float | None, str]]:
    """Work out the settlement lines that follow from data we already hold.

    Asking Finance to type nine numbers per person is data entry, not a
    product — and four of the nine follow arithmetically from the salary,
    leave balance and service length already on the employee profile. Those
    are computed and marked as such; Finance overrides anything wrong.

    The remaining lines genuinely cannot be derived — nobody can guess an
    expense claim — and stay blank rather than being filled with a plausible
    zero. Returns {label: (amount_or_None, how_it_was_worked_out)}.

    Daily rate is monthly / 26, the same basis the Notice Period Policy uses
    for buyout, so a shortfall here and a buyout there agree.
    """
    if not profile or not profile.get("basic_salary"):
        return {}

    salary = float(profile["basic_salary"])
    daily = salary / 26
    leave_days = int(profile.get("leave_balance_days") or 0)
    years = float(profile.get("years_of_service") or 0)

    out: dict[str, tuple[float | None, str]] = {}

    # Final month, paid to the last working day.
    last_day = date.fromisoformat(str(case["last_working_day"])[:10])
    days_in_month = monthrange(last_day.year, last_day.month)[1]
    worked = last_day.day
    out["Salary up to last working day"] = (
        round(salary * worked / days_in_month, 2),
        f"{worked} of {days_in_month} days in {last_day.strftime('%B')} "
        f"at {salary:,.0f}/month",
    )

    if leave_days:
        out["Leave encashment"] = (
            round(daily * leave_days, 2),
            f"{leave_days} days at {daily:,.2f}/day (monthly / 26)",
        )

    # Gratuity: the statutory 15 days' wages per completed year, after five.
    if years >= 5:
        out["Gratuity (if eligible)"] = (
            round((15 / 26) * salary * int(years), 2),
            f"15/26 x {salary:,.0f} x {int(years)} completed years",
        )
    else:
        out["Gratuity (if eligible)"] = (
            None,
            f"Not eligible — {years} years of service, five required",
        )

    # Shortfall only where notice actually fell short.
    required = int(profile.get("notice_period_days") or case.get("notice_period_days") or 0)
    served = (last_day - date.fromisoformat(str(case["resignation_date"])[:10])).days
    unserved = max(0, required - served)
    if unserved:
        out["Notice period shortfall"] = (
            round(daily * unserved, 2),
            f"{unserved} days short of {required} at {daily:,.2f}/day",
        )
    else:
        out["Notice period shortfall"] = (
            None,
            f"Full notice served — {served} of {required} days",
        )

    return out


def open_clearance_detail(case_id: str, employee: dict[str, Any]) -> dict[str, int]:
    """Create the itemised lists for a case. Safe to call twice — a case that
    already has rows of a given kind is left alone, so a re-run tops up a case
    created before this existed rather than duplicating one that has them."""
    db = service_db()
    department = employee.get("department") or ""
    designation = employee.get("designation") or ""
    created = {"assets": 0, "access": 0, "settlement": 0}

    # The HR profile holds the real inventory — models, serial numbers, and the
    # access role held on each system. Prefer it. The department lists above are
    # a fallback for anyone without a profile, and say "probably holds" rather
    # than "holds".
    found = (
        db.table("employee_profiles")
        .select("*")
        .eq("employee_id", employee.get("id"))
        .limit(1)
        .execute()
    )
    profile = found.data[0] if found.data else None

    if not db.table("case_assets").select("id").eq("case_id", case_id).limit(1).execute().data:
        inventory = (profile or {}).get("assigned_assets") or []
        if inventory:
            rows = [
                {
                    "case_id": case_id,
                    "name": f"{item.get('model') or item.get('type', 'Item')}",
                    "category": item.get("type") or "other",
                    "identifier": item.get("serial"),
                    "note": f"Condition when issued: {item['condition']}"
                    if item.get("condition")
                    else None,
                    "sort_order": i,
                }
                for i, item in enumerate(inventory)
            ]
        else:
            rows = [
                {"case_id": case_id, "name": name, "category": category, "sort_order": i}
                for i, (name, category) in enumerate(_assets_for(department))
            ]
        db.table("case_assets").insert(rows).execute()
        created["assets"] = len(rows)

    if not db.table("case_access").select("id").eq("case_id", case_id).limit(1).execute().data:
        held = (profile or {}).get("system_access") or []
        if held:
            rows = [
                {
                    "case_id": case_id,
                    "system": item.get("system", "Unknown system"),
                    "category": "identity"
                    if "sso" in str(item.get("system", "")).lower()
                    else "engineering",
                    # The access role is the signal IT needs: an admin account
                    # goes on the last day, a read-only one can wait.
                    "is_elevated": str(item.get("role", "")).lower()
                    in ("admin", "owner", "approver"),
                    "note": f"Held as: {item['role']}" if item.get("role") else None,
                    "sort_order": i,
                }
                for i, item in enumerate(held)
            ]
        else:
            rows = [
                {
                    "case_id": case_id,
                    "system": system,
                    "category": category,
                    "is_elevated": elevated,
                    "sort_order": i,
                }
                for i, (system, category, elevated) in enumerate(
                    _access_for(department, designation)
                )
            ]
        db.table("case_access").insert(rows).execute()
        created["access"] = len(rows)

    if not db.table("case_settlement").select("id").eq("case_id", case_id).limit(1).execute().data:
        case = (
            db.table("exit_cases")
            .select("last_working_day, resignation_date, notice_period_days")
            .eq("id", case_id)
            .single()
            .execute()
        ).data
        computed = compute_settlement(profile, case)

        rows = []
        for i, (kind, label) in enumerate(_SETTLEMENT_LINES):
            amount, basis = computed.get(label, (None, ""))
            rows.append(
                {
                    "case_id": case_id,
                    "kind": kind,
                    "label": label,
                    "sort_order": i,
                    "amount": amount,
                    # Computed lines arrive confirmed so Finance reviews rather
                    # than retypes; a line we could not derive stays pending and
                    # visibly empty.
                    "status": "confirmed" if amount is not None else "pending",
                    "note": basis or None,
                }
            )
        db.table("case_settlement").insert(rows).execute()
        created["settlement"] = len(rows)

    return created
