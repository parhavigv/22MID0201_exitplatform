"""Seed ten additional exiting employees, each parked at a different stage.

Why this exists
---------------
`supabase/seed.sql` creates ten people but only one open exit case, so every
HR screen — Progress, Overdue, All cases, Analytics — renders with a single
row. This script fills the board out: ten more employees, each with a case
sitting at a different point in the ten-stage workflow, so the dashboards show
the spread of work they were designed to show.

Everyone added here is an `employee`. The single manager (Arjun Menon) and the
single HR partner (Priya Nair) already exist in the seed and are reused, not
duplicated — every new report rolls up to Arjun, so his "Team exits" view
shows all ten.

Consistency, not just volume
----------------------------
A case parked at IT_CLEARANCE with every task still `pending` would look wrong
on screen and would teach the agent nothing. So each case is back-filled to
match its stage: tasks in stages already passed are completed, anything still
open past its due date is flagged SLA-breached, KT coverage tracks how far the
handover should have got, and cases at or past EXIT_INTERVIEW carry real
interview responses.

Auth users are written with direct SQL rather than through supabase-py: the
password has to be bcrypt-hashed by Postgres (`crypt(..., gen_salt('bf'))`)
and paired with an `auth.identities` row, which is exactly what seed.sql
already does. This mirrors that block instead of inventing a second pattern.

Usage
-----
    cd backend
    .venv/Scripts/python.exe scripts/seed_more_employees.py

    # Remove everything this script created (cases, tasks, employees, logins):
    .venv/Scripts/python.exe scripts/seed_more_employees.py --undo

Re-running is safe. A person whose emp_code already exists is skipped, so the
script tops up what is missing rather than duplicating anyone.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import psycopg  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.deps import service_db  # noqa: E402

DEMO_PASSWORD = "ExitDemo!2026"
MANAGER_EMAIL = "arjun.menon@example.com"
HR_EMAIL = "priya.nair@example.com"

STAGE_ORDER = [
    "RESIGNATION_SUBMITTED",
    "MANAGER_ACK",
    "KT_PLANNING",
    "KT_EXECUTION",
    "IT_CLEARANCE",
    "FINANCE_CLEARANCE",
    "ADMIN_ASSET_RETURN",
    "EXIT_INTERVIEW",
    "FINAL_SETTLEMENT",
    "RELIEVING_LETTER",
]


class Person:
    """One seeded employee and the exit case they should end up with.

    `elapsed` is how many days into the notice period "today" is. Resignation
    and last-working-day are derived from it so the case stays plausible
    whenever the script is run, rather than drifting as fixed dates age.
    """

    def __init__(
        self, code, name, email, department, designation, doj,
        stage, notice, elapsed, exit_type="resignation", status="active",
    ):
        self.code = code
        self.name = name
        self.email = email
        self.department = department
        self.designation = designation
        self.doj = doj
        self.stage = stage
        self.notice = notice
        self.elapsed = elapsed
        self.exit_type = exit_type
        self.status = status

    @property
    def resignation_date(self) -> date:
        return date.today() - timedelta(days=self.elapsed)

    @property
    def last_working_day(self) -> date:
        return self.resignation_date + timedelta(days=self.notice)


# `elapsed` is calibrated against the task templates, not the notice period.
# Template offsets top out at 42 days, so a case 50 days into a 60-day notice
# has every remaining task past its due date and reads as broken rather than
# busy. Each person sits just past their own stage's offset, which leaves a
# couple of genuinely overdue tasks instead of a wall of them. Tanvi is the
# deliberate exception — an on-hold case is supposed to look badly behind.
PEOPLE = [
    Person("EMP-0011", "Aditya Sharma", "aditya.sharma@example.com",
           "Engineering", "Engineer I", "2023-06-12",
           "RESIGNATION_SUBMITTED", 30, 1),
    Person("EMP-0012", "Nandini Reddy", "nandini.reddy@example.com",
           "Engineering", "Senior Engineer", "2020-02-17",
           "MANAGER_ACK", 60, 4),
    Person("EMP-0013", "Farhan Qureshi", "farhan.qureshi@example.com",
           "Engineering", "Principal Engineer", "2017-08-21",
           "KT_PLANNING", 90, 12),
    Person("EMP-0014", "Ishita Banerjee", "ishita.banerjee@example.com",
           "Quality Assurance", "QA Lead", "2021-11-08",
           "KT_EXECUTION", 60, 20),
    Person("EMP-0015", "Rohan Kulkarni", "rohan.kulkarni@example.com",
           "DevOps", "Site Reliability Engineer", "2019-05-20",
           "IT_CLEARANCE", 45, 26),
    Person("EMP-0016", "Divya Pillai", "divya.pillai@example.com",
           "Data & Analytics", "Senior Data Analyst", "2020-09-14",
           "FINANCE_CLEARANCE", 60, 30),
    Person("EMP-0017", "Sameer Khan", "sameer.khan@example.com",
           "Engineering", "Engineering Architect", "2016-03-07",
           "EXIT_INTERVIEW", 45, 33, exit_type="retirement"),
    Person("EMP-0018", "Ananya Ghosh", "ananya.ghosh@example.com",
           "Quality Assurance", "QA Engineer", "2022-04-25",
           "FINAL_SETTLEMENT", 45, 41),
    Person("EMP-0019", "Vivek Nair", "vivek.nair@example.com",
           "Data & Analytics", "Analytics Engineer", "2021-01-18",
           "RELIEVING_LETTER", 45, 50,
           exit_type="end_of_contract", status="completed"),
    Person("EMP-0020", "Tanvi Mehta", "tanvi.mehta@example.com",
           "DevOps", "Platform Engineer", "2023-09-05",
           "KT_EXECUTION", 60, 33, status="on_hold"),
]

KT_TOPICS = {
    "Engineering": [
        ("Service ownership and deploys", "Repos owned, release process, and rollback steps."),
        ("On-call runbook", "Paging rules, common alerts, and escalation contacts."),
        ("In-flight work", "Open branches, review state, and what 'done' looks like."),
        ("Vendor and API contacts", "Third-party integrations and who owns each relationship."),
    ],
    "Quality Assurance": [
        ("Regression suite ownership", "Suite layout, flaky tests, and the nightly schedule."),
        ("Release sign-off process", "Gates, who approves, and the evidence required."),
        ("Test environments", "Provisioning, seed data, and known limitations."),
    ],
    "DevOps": [
        ("Infrastructure as code", "Terraform layout, state storage, and apply process."),
        ("Monitoring and alerting", "Dashboards, alert routes, and tuning history."),
        ("Secrets and access management", "Vault structure and rotation schedule."),
        ("Disaster recovery runbook", "Backup verification and restore drill notes."),
    ],
    "Data & Analytics": [
        ("Pipeline ownership", "DAG structure, upstream dependencies, and SLAs."),
        ("Reporting models", "Metric definitions and which dashboards consume them."),
        ("Data quality checks", "Known gaps and the reconciliation process."),
    ],
}

INTERVIEW_RESPONSES = {
    "EMP-0017": {
        "reason_for_leaving": "Retiring after nine years; this is a planned exit, not a departure prompted by anything at work.",
        "role_and_responsibilities": "The architect role matched what was described and grew well over time.",
        "manager_and_team": "Strong team. Arjun gave real autonomy and backed technical decisions.",
        "growth_and_development": "Plenty of scope to grow technically. Less clarity on the non-management senior track.",
        "compensation_and_benefits": "Fair and reviewed regularly.",
        "organisation_and_culture": "Keep the engineering review culture. The planning cycle changes direction too often mid-quarter.",
        "anything_else": "Happy to stay available for architecture questions during the first quarter after I leave.",
    },
    "EMP-0018": {
        "reason_for_leaving": "Offered a QA lead position elsewhere; wanted the step up sooner than it was available here.",
        "role_and_responsibilities": "Accurate to the job description, though the scope widened without the title changing.",
        "manager_and_team": "Supportive manager, good peers. One-to-ones were sometimes cancelled during crunch.",
        "growth_and_development": "Limited. The lead path was unclear and kept moving.",
        "compensation_and_benefits": "Slightly below market for the scope I was carrying.",
        "organisation_and_culture": "Keep the blameless postmortems. Address how often releases slip into the weekend.",
        "anything_else": "The regression suite needs a dedicated owner after I go.",
    },
    "EMP-0019": {
        "reason_for_leaving": "Fixed-term contract reached its end date.",
        "role_and_responsibilities": "Clear from the start, and the scope stayed stable.",
        "manager_and_team": "Well integrated with the permanent team; never treated as an outsider.",
        "growth_and_development": "Learned a lot about the data stack in a short contract.",
        "compensation_and_benefits": "As agreed in the contract.",
        "organisation_and_culture": "Onboarding for contractors could be faster — took three weeks to get full data access.",
        "anything_else": "Would consider a permanent role here in future.",
    },
}

INTERVIEW_ANALYSIS = {
    "EMP-0017": ("positive",
                 ["planned retirement", "strong technical autonomy", "unclear senior IC track",
                  "shifting quarterly priorities"],
                 "A planned retirement with consistently positive feedback. Praises engineering "
                 "autonomy and review culture. Two structural themes worth noting: the "
                 "non-management senior track lacks definition, and quarterly planning changes "
                 "direction mid-cycle. Offers post-exit availability for architecture questions."),
    "EMP-0018": ("mixed",
                 ["career progression blocked", "title lagged scope", "below-market compensation",
                  "release schedule spilling into weekends"],
                 "Regretted attrition. Left for a lead title that was not available internally on a "
                 "clear timeline. Scope grew without a matching title or pay adjustment, and "
                 "release slippage into weekends is raised as a recurring strain. Flags the "
                 "regression suite as needing a named owner."),
    "EMP-0019": ("positive",
                 ["contract concluded as planned", "well integrated", "slow contractor onboarding"],
                 "Routine end-of-contract exit with positive sentiment. Only actionable theme is "
                 "contractor onboarding: full data access took three weeks. Open to returning in a "
                 "permanent capacity."),
}


# ---------------------------------------------------------------------------
# Auth users + employees (direct SQL — see module docstring)
# ---------------------------------------------------------------------------

_INSTANCE_ID = "00000000-0000-0000-0000-000000000000"

_INSERT_AUTH_USER = """
insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password,
  email_confirmed_at, raw_app_meta_data, raw_user_meta_data,
  created_at, updated_at,
  confirmation_token, email_change, email_change_token_new, recovery_token
) values (
  %(instance)s::uuid, gen_random_uuid(), 'authenticated', 'authenticated', %(email)s::text,
  crypt(%(password)s::text, gen_salt('bf')),
  now(),
  '{"provider":"email","providers":["email"]}'::jsonb,
  jsonb_build_object('full_name', %(name)s::text),
  now(), now(), '', '', '', ''
)
returning id;
"""

_INSERT_IDENTITY = """
insert into auth.identities (
  id, user_id, provider_id, identity_data, provider,
  last_sign_in_at, created_at, updated_at
) values (
  gen_random_uuid(), %(auth_id)s::uuid, %(auth_id)s::text,
  jsonb_build_object('sub', %(auth_id)s::text, 'email', %(email)s::text, 'email_verified', true),
  'email', now(), now(), now()
);
"""

_UPSERT_EMPLOYEE = """
insert into employees (
  auth_user_id, emp_code, full_name, work_email,
  department, designation, date_of_joining, manager_id, app_role
) values (
  %(auth_id)s, %(code)s, %(name)s, %(email)s,
  %(department)s, %(designation)s, %(doj)s::date, %(manager_id)s, 'employee'
)
on conflict (emp_code) do update set
  auth_user_id = excluded.auth_user_id,
  full_name    = excluded.full_name,
  department   = excluded.department,
  designation  = excluded.designation,
  manager_id   = excluded.manager_id;
"""


def upsert_people(conn) -> None:
    """Create each login and employee row, reusing any account that already exists."""
    row = conn.execute(
        "select id from employees where work_email = %s", (MANAGER_EMAIL,)
    ).fetchone()
    if not row:
        raise SystemExit(
            f"Manager {MANAGER_EMAIL} not found — run scripts/apply_migrations.py --seed first."
        )
    manager_id = row[0]

    for p in PEOPLE:
        found = conn.execute(
            "select id from auth.users where email = %s", (p.email,)
        ).fetchone()

        if found:
            auth_id = found[0]
            # Reset to the documented demo password so the credentials always work.
            conn.execute(
                "update auth.users set encrypted_password = crypt(%s, gen_salt('bf')), "
                "email_confirmed_at = coalesce(email_confirmed_at, now()), updated_at = now() "
                "where id = %s",
                (DEMO_PASSWORD, auth_id),
            )
        else:
            auth_id = conn.execute(_INSERT_AUTH_USER, {
                "instance": _INSTANCE_ID,
                "email": p.email,
                "password": DEMO_PASSWORD,
                "name": p.name,
            }).fetchone()[0]
            # Required for email/password sign-in on current Supabase Auth.
            conn.execute(_INSERT_IDENTITY, {"auth_id": auth_id, "email": p.email})

        conn.execute(_UPSERT_EMPLOYEE, {
            "auth_id": auth_id,
            "code": p.code,
            "name": p.name,
            "email": p.email,
            "department": p.department,
            "designation": p.designation,
            "doj": p.doj,
            "manager_id": manager_id,
        })

    conn.commit()


# ---------------------------------------------------------------------------
# Cases, tasks, KT, interviews
# ---------------------------------------------------------------------------


def build_case(db, person: Person, emp: dict, manager_id: str, hr_id: str) -> str | None:
    """Create one exit case and everything hanging off it."""
    existing = (
        db.table("exit_cases").select("id")
        .eq("employee_id", emp["id"]).limit(1).execute()
    )
    if existing.data:
        return None

    today = date.today()
    resignation = person.resignation_date
    lwd = person.last_working_day
    stage_idx = STAGE_ORDER.index(person.stage)

    case = db.table("exit_cases").insert({
        "employee_id": emp["id"],
        "exit_type": person.exit_type,
        "resignation_date": resignation.isoformat(),
        "last_working_day": lwd.isoformat(),
        "notice_period_days": person.notice,
        "current_stage": person.stage,
        "status": person.status,
        "created_by": emp["id"],
    }).execute().data[0]
    case_id = case["id"]

    # --- tasks: expand the template, then age them to match the stage -------
    templates = (
        db.table("task_templates").select("*")
        .eq("is_active", True).order("sort_order").execute().data
    )
    rows = []
    for t in templates:
        t_idx = STAGE_ORDER.index(t["stage_code"]) if t["stage_code"] in STAGE_ORDER else 99
        due = min(resignation + timedelta(days=t["offset_days"]), lwd)

        if t_idx < stage_idx or person.status == "completed":
            status, completed_at = "completed", due.isoformat()
        else:
            status, completed_at = "pending", None

        rows.append({
            "case_id": case_id,
            "stage_code": t["stage_code"],
            "template_id": t["id"],
            "title": t["title"],
            "description": t["description"],
            "owner_role": t["owner_role"],
            "assignee_id": emp["id"] if t["owner_role"] == "employee" else None,
            "doc_type_code": t["doc_type_code"],
            "due_date": due.isoformat(),
            "status": status,
            "completed_at": completed_at,
            "completed_by": (
                emp["id"] if status == "completed" and t["owner_role"] == "employee"
                else manager_id if status == "completed" else None
            ),
            # An open task past its due date is what the Overdue board is for.
            "sla_breached": status == "pending" and due < today,
            "sort_order": t["sort_order"],
            "origin": "template",
        })
    db.table("case_tasks").insert(rows).execute()

    # --- approvals for every stage already signed off ----------------------
    approvals = [
        {
            "case_id": case_id,
            "stage_code": code,
            "approver_id": hr_id if code in ("EXIT_INTERVIEW", "RELIEVING_LETTER") else manager_id,
            "decision": "approved",
            "comment": "Stage cleared.",
        }
        for code in STAGE_ORDER[:stage_idx]
    ]
    if approvals:
        db.table("approvals").insert(approvals).execute()

    # --- knowledge transfer -------------------------------------------------
    if stage_idx < STAGE_ORDER.index("KT_PLANNING"):
        kt_overall, item_status = "not_started", "not_started"
    elif stage_idx == STAGE_ORDER.index("KT_PLANNING"):
        kt_overall, item_status = "in_progress", "in_progress"
    elif stage_idx == STAGE_ORDER.index("KT_EXECUTION"):
        kt_overall, item_status = "in_progress", "documented"
    else:
        kt_overall, item_status = "verified", "verified"

    kt = db.table("kt_records").insert({
        "case_id": case_id,
        "overall_status": kt_overall,
        "successor_id": manager_id if stage_idx >= STAGE_ORDER.index("KT_PLANNING") else None,
        "reviewed_by": manager_id if kt_overall == "verified" else None,
        "reviewed_at": "now()" if kt_overall == "verified" else None,
    }).execute().data[0]

    topics = KT_TOPICS.get(person.department, KT_TOPICS["Engineering"])
    items = []
    for i, (topic, detail) in enumerate(topics, start=1):
        # One honest gap on a finished handover is more realistic — and more
        # useful to demo — than a wall of green.
        is_gap = item_status == "verified" and i == len(topics)
        items.append({
            "kt_record_id": kt["id"],
            "topic": topic,
            "detail": detail,
            "coverage_status": "gap" if is_gap else item_status,
            "gap_note": (
                "Not fully transferred before the last working day; interim owner is the manager."
                if is_gap else None
            ),
            "sort_order": i,
        })
    db.table("kt_items").insert(items).execute()

    # --- exit interview -----------------------------------------------------
    interview: dict = {"case_id": case_id}
    if person.code in INTERVIEW_RESPONSES:
        sentiment, themes, summary = INTERVIEW_ANALYSIS[person.code]
        interview.update({
            "responses": INTERVIEW_RESPONSES[person.code],
            "submitted_at": "now()",
            "sentiment": sentiment,
            "themes": themes,
            "summary": summary,
            "analysed_at": "now()",
        })
    db.table("exit_interviews").insert(interview).execute()

    return case_id


def seed() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("ERROR: DATABASE_URL is not set in backend/.env")
        return 1

    print("Creating logins and employee records...")
    with psycopg.connect(settings.database_url) as conn:
        upsert_people(conn)
    print(f"  {len(PEOPLE)} employees ready.")

    db = service_db()
    manager_id = db.table("employees").select("id").eq("work_email", MANAGER_EMAIL).single().execute().data["id"]
    hr_id = db.table("employees").select("id").eq("work_email", HR_EMAIL).single().execute().data["id"]

    print("\nBuilding exit cases:")
    created = skipped = 0
    for p in PEOPLE:
        emp = db.table("employees").select("*").eq("emp_code", p.code).single().execute().data
        case_id = build_case(db, p, emp, manager_id, hr_id)
        if case_id is None:
            print(f"  = {p.code} {p.name:<18} already has a case — skipped")
            skipped += 1
        else:
            print(f"  + {p.code} {p.name:<18} {p.stage:<22} "
                  f"LWD {p.last_working_day}  ({p.status})")
            created += 1

    print(f"\nDone. {created} case(s) created, {skipped} skipped.")
    print(f"All logins use the password: {DEMO_PASSWORD}")
    return 0


def undo() -> int:
    """Remove everything this script created."""
    db = service_db()
    codes = [p.code for p in PEOPLE]
    emps = db.table("employees").select("id, emp_code, auth_user_id").in_("emp_code", codes).execute().data
    if not emps:
        print("Nothing to remove.")
        return 0

    ids = [e["id"] for e in emps]
    cases = db.table("exit_cases").select("id").in_("employee_id", ids).execute().data
    for c in cases:
        # audit_log has no cascade from exit_cases, so clear it explicitly.
        db.table("audit_log").delete().eq("case_id", c["id"]).execute()
    db.table("exit_cases").delete().in_("employee_id", ids).execute()

    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.execute("delete from employees where emp_code = any(%s)", (codes,))
        conn.execute(
            "delete from auth.users where id = any(%s)",
            ([e["auth_user_id"] for e in emps if e["auth_user_id"]],),
        )
        conn.commit()

    print(f"Removed {len(emps)} employee(s), {len(cases)} case(s), and their logins.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--undo", action="store_true", help="Remove everything this script created.")
    args = parser.parse_args()
    raise SystemExit(undo() if args.undo else seed())
