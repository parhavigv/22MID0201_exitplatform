"""Give every employee an HR profile: salary, leave, assets, system access.

Why this is needed
------------------
Migration 0006 created profiles for the three people who existed at the time.
Twelve more have been added since and have none, which matters more than it
sounds: the profile is where `basic_salary`, `leave_balance_days` and
`years_of_service` live, and those are what let the settlement screen compute a
figure instead of asking Finance to type one. Without a profile every amount is
blank and somebody keys in nine numbers per person by hand.

It also holds `assigned_assets` and `system_access` as real inventories — with
models, serial numbers and access roles — which is strictly better than the
"someone in Engineering probably has a monitor" guess in services/clearance.py.

What the numbers are
--------------------
Invented, and consistent rather than accurate. Salary follows the grade implied
by the designation, leave balance and service years are derived from the date of
joining, and the asset and access lists follow the department. No real payroll
system is connected, so this is demo data that behaves sensibly — not a claim
about anyone's pay.

Re-running is safe: people who already have a profile are left untouched, so
the three seeded in 0006 keep their hand-written detail.

Usage
-----
    cd backend
    .venv/Scripts/python.exe scripts/seed_employee_profiles.py
    .venv/Scripts/python.exe scripts/seed_employee_profiles.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.deps import service_db  # noqa: E402

# Designation keyword -> (grade, monthly basic, notice days). First match wins,
# so the more senior titles are listed first.
GRADES: list[tuple[tuple[str, ...], tuple[str, float, int]]] = [
    (("head", "director"), ("L7", 210000.0, 90)),
    (("principal", "architect"), ("L6", 175000.0, 90)),
    (("manager", "lead"), ("L6", 150000.0, 90)),
    (("staff",), ("L6", 160000.0, 90)),
    (("senior",), ("L5", 115000.0, 60)),
    (("analyst", "engineer", "executive", "administrator"), ("L4", 85000.0, 60)),
    (("associate", "rep", "i", "trainee"), ("L3", 55000.0, 30)),
]

ASSETS_BY_DEPARTMENT: dict[str, list[tuple[str, str]]] = {
    "Engineering": [("laptop", 'MacBook Pro 14"'), ("monitor", 'Dell 27" 4K'), ("headset", "Jabra Evolve2")],
    "DevOps": [("laptop", 'MacBook Pro 16"'), ("monitor", 'LG 27" 4K'), ("token", "YubiKey 5")],
    "Quality Assurance": [("laptop", 'MacBook Air 13"'), ("mobile", "Pixel 7 test device"), ("headset", "Jabra Evolve2")],
    "Data & Analytics": [("laptop", 'MacBook Pro 14"'), ("monitor", 'Dell 24" FHD')],
    "Sales": [("laptop", 'MacBook Air 13"'), ("mobile", "iPhone 14"), ("sim", "Airtel corporate SIM")],
    "Finance": [("laptop", "ThinkPad X1 Carbon"), ("monitor", 'Dell 24" FHD')],
    "IT": [("laptop", "ThinkPad X1 Carbon"), ("token", "YubiKey 5"), ("monitor", 'Dell 27" 4K')],
    "Human Resources": [("laptop", 'MacBook Air 13"'), ("mobile", "iPhone 14")],
}

ACCESS_BY_DEPARTMENT: dict[str, list[tuple[str, str]]] = {
    "Engineering": [("GitHub (org)", "member"), ("AWS Staging", "admin"), ("AWS Production", "read"), ("Jira", "member"), ("PagerDuty", "responder")],
    "DevOps": [("GitHub (org)", "admin"), ("AWS Production", "admin"), ("Vault", "admin"), ("PagerDuty", "admin"), ("Terraform Cloud", "admin")],
    "Quality Assurance": [("GitHub (org)", "member"), ("Jira", "admin"), ("TestRail", "admin"), ("Staging environments", "member")],
    "Data & Analytics": [("Snowflake", "admin"), ("dbt Cloud", "member"), ("Looker", "admin"), ("GitHub (org)", "member")],
    "Sales": [("Salesforce CRM", "member"), ("Gong", "member"), ("LinkedIn Sales Navigator", "user")],
    "Finance": [("Workday Financials", "admin"), ("Coupa", "member"), ("Corporate banking portal", "approver")],
    "IT": [("Okta", "admin"), ("Intune", "admin"), ("Active Directory", "admin"), ("Zoom admin", "admin")],
    "Human Resources": [("Workday HRMS", "admin"), ("Darwinbox", "admin"), ("Greenhouse", "admin")],
}

COMMON_ACCESS: list[tuple[str, str]] = [
    ("Okta SSO", "user"),
    ("Google Workspace", "user"),
    ("Slack", "member"),
    ("Confluence", "member"),
    ("VPN", "user"),
]


def grade_for(designation: str) -> tuple[str, float, int]:
    text = (designation or "").lower()
    for keywords, result in GRADES:
        if any(k in text.split() or k in text for k in keywords):
            return result
    return ("L4", 85000.0, 60)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = service_db()
    employees = db.table("employees").select("*").order("emp_code").execute().data
    have = {
        p["employee_id"]
        for p in db.table("employee_profiles").select("employee_id").execute().data
    }

    today = date.today()
    created = 0

    for e in employees:
        if e["id"] in have:
            print(f"  = {e['emp_code']} {e['full_name']:<18} already has a profile")
            continue

        department = e.get("department") or ""
        grade, salary, notice = grade_for(e.get("designation") or "")
        joined = date.fromisoformat(str(e["date_of_joining"])[:10])
        years = round((today - joined).days / 365.25, 1)
        # Roughly two days accrued per month of service, capped the way most
        # policies cap carry-forward.
        leave = min(30, max(4, int(years * 2.5) % 28 + 4))

        assets = [
            {
                "type": kind,
                "model": model,
                "serial": f"{kind[:3].upper()}-{e['emp_code'].split('-')[1]}",
                "condition": "good",
            }
            for kind, model in ASSETS_BY_DEPARTMENT.get(department, ASSETS_BY_DEPARTMENT["Engineering"])
        ]
        access = [
            {"system": system, "role": role}
            for system, role in COMMON_ACCESS
            + ACCESS_BY_DEPARTMENT.get(department, ACCESS_BY_DEPARTMENT["Engineering"])
        ]

        print(
            f"  + {e['emp_code']} {e['full_name']:<18}{grade}  "
            f"{salary:>9,.0f}/mo  {leave:>2} days leave  "
            f"{years:>4} yrs  {len(assets)} assets  {len(access)} systems"
        )
        created += 1
        if args.dry_run:
            continue

        db.table("employee_profiles").insert(
            {
                "employee_id": e["id"],
                "basic_salary": salary,
                "grade": grade,
                "employment_type": "permanent",
                "notice_period_days": notice,
                "leave_balance_days": leave,
                "personal_email": e["work_email"].replace("@example.com", ".personal@gmail.com"),
                "phone": f"+91-98400-{e['emp_code'].split('-')[1]}",
                "work_location": "Bangalore",
                "assigned_assets": assets,
                "system_access": access,
                "years_of_service": years,
            }
        ).execute()

    if not created:
        print("\nEveryone already has a profile.")
    elif args.dry_run:
        print(f"\n{created} profile(s) would be created. Re-run without --dry-run.")
    else:
        print(f"\n{created} profile(s) created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
