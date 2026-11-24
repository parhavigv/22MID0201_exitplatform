"""
Prove RLS actually isolates users.

Signs in as real seeded accounts through Supabase Auth and queries as them, so
this exercises the same path the app does: a token, PostgREST, and the policies
in 0002_rls.sql. Nothing here uses the service role.

This is the Phase 0 "done when" criterion, and the seed of the Phase 9 suite.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.deps import service_db  # noqa: E402
from scripts import _fixtures  # noqa: E402
from scripts.apply_migrations import connect as db_connect  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "backend" / ".env")

URL = os.environ["SUPABASE_URL"]
ANON = os.environ["SUPABASE_ANON_KEY"]
PASSWORD = "ExitDemo!2026"

# The suite deletes its subject's case on every run, and deleting a case
# cascades to that person's documents — pointed at a real demo employee it
# silently wiped their uploads. Use a throwaway account instead.
SUBJECT = _fixtures.SUBJECT  # employee with a case, reports to Arjun
ARJUN = "arjun.menon@example.com"  # the only manager
PRIYA = "priya.nair@example.com"  # HR

# The demo roster has no employee without a case and no second manager, and
# both are needed to prove isolation holds. The suite creates them itself and
# removes them at the end — see scripts/_fixtures.py.
RAHUL = _fixtures.PEER  # employee with no case, reports to Arjun
VIKRAM = _fixtures.OTHER_MANAGER  # manager of a different team

passed = 0
failed = 0


def check(label: str, actual: object, expected: object) -> None:
    global passed, failed
    ok = actual == expected
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  (expected {expected!r}, got {actual!r})")


def client_for(email: str):
    """Sign in, retrying briefly on a throttled auth call.

    Five users sign in back to back and Supabase Auth rate-limits by IP. A
    throttled sign-in would otherwise fail an assertion about isolation, which
    is not what went wrong. Retry the sign-in; never the assertions.
    """
    last: Exception | None = None
    for attempt in range(4):
        try:
            c = create_client(URL, ANON)
            c.auth.sign_in_with_password({"email": email, "password": PASSWORD})
            return c
        except Exception as exc:  # noqa: BLE001 - retried below, re-raised at the end
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Could not sign in as {email} after 4 attempts: {last}")


def clear_test_cases() -> None:
    """Remove cases left by a previous run.

    Must go through a direct connection: there is deliberately no DELETE policy
    on exit_cases — a real case is cancelled, never erased — so RLS silently
    drops the delete and `exit_cases_one_open_per_employee` then blocks the
    next run.
    """
    conn = db_connect()
    with conn.cursor() as cur:
        cur.execute(
            """
            delete from exit_cases
            where employee_id in (select id from employees where work_email = %s)
            """,
            (SUBJECT,),
        )
        conn.commit()
    _fixtures.remove(conn)
    conn.close()


def main() -> int:
    clear_test_cases()  # re-runnable regardless of how a previous run ended
    conn = db_connect()
    _fixtures.ensure(conn)
    conn.close()
    print("Signing in as seeded users...\n")
    try:
        subject = client_for(SUBJECT)
        rahul = client_for(RAHUL)
        arjun = client_for(ARJUN)
        vikram = client_for(VIKRAM)
        priya = client_for(PRIYA)
    except Exception as exc:
        print(f"Sign-in failed: {exc}")
        print("\nIf this is 'Invalid login credentials', the seed's auth users")
        print("did not take. Check Authentication -> Users in the dashboard.")
        return 1

    print("employees\n")
    check(
        "employee sees only self, manager, and reports",
        {r["work_email"] for r in subject.table("employees").select("work_email").execute().data},
        {SUBJECT, ARJUN},
    )
    # Expectations are derived from the database, not hardcoded. Seeding extra
    # demo employees (scripts/seed_more_employees.py) is a normal thing to do,
    # and a fixed roster here would fail on correct behaviour every time it
    # happens — which teaches people to ignore this suite. What matters is that
    # the boundary holds: exactly self plus direct reports, and for HR everyone.
    admin = service_db()
    arjun_id = (
        admin.table("employees").select("id").eq("work_email", ARJUN).single().execute().data["id"]
    )
    expected_for_arjun = {ARJUN} | {
        r["work_email"]
        for r in admin.table("employees").select("work_email").eq("manager_id", arjun_id).execute().data
    }
    check(
        "manager sees self and direct reports",
        {r["work_email"] for r in arjun.table("employees").select("work_email").execute().data},
        expected_for_arjun,
    )
    check(
        "HR sees everyone",
        len(priya.table("employees").select("id").execute().data),
        admin.table("employees").select("id", count="exact").limit(1).execute().count,
    )

    print("\nexit_cases — create one as the subject, then check who can see it\n")

    created = (
        subject.table("exit_cases")
        .insert(
            {
                "employee_id": subject.table("employees")
                .select("id")
                .eq("work_email", SUBJECT)
                .execute()
                .data[0]["id"],
                "resignation_date": "2026-09-01",
                "last_working_day": "2026-10-31",
                "notice_period_days": 60,
                "current_stage": "RESIGNATION_SUBMITTED",
                "status": "active",
            }
        )
        .execute()
    )
    check("employee can open their own case", len(created.data), 1)
    case_id = created.data[0]["id"]

    check(
        "owner sees their case",
        len(subject.table("exit_cases").select("id").eq("id", case_id).execute().data),
        1,
    )
    check(
        "their manager sees it",
        len(arjun.table("exit_cases").select("id").eq("id", case_id).execute().data),
        1,
    )
    check(
        "HR sees it",
        len(priya.table("exit_cases").select("id").eq("id", case_id).execute().data),
        1,
    )
    check(
        "a peer cannot see it",
        len(rahul.table("exit_cases").select("id").eq("id", case_id).execute().data),
        0,
    )
    check(
        "another team's manager cannot see it",
        len(vikram.table("exit_cases").select("id").eq("id", case_id).execute().data),
        0,
    )

    print("\nwrite protection\n")

    # The exiting employee must not advance their own case.
    moved = (
        subject.table("exit_cases")
        .update({"current_stage": "RELIEVING_LETTER"})
        .eq("id", case_id)
        .execute()
    )
    check("employee cannot advance their own case", len(moved.data), 0)

    moved_by_manager = (
        arjun.table("exit_cases")
        .update({"current_stage": "MANAGER_ACK"})
        .eq("id", case_id)
        .execute()
    )
    check("their manager can advance it", len(moved_by_manager.data), 1)

    hijack = (
        vikram.table("exit_cases")
        .update({"current_stage": "RELIEVING_LETTER"})
        .eq("id", case_id)
        .execute()
    )
    check("another team's manager cannot advance it", len(hijack.data), 0)

    print("\nreference data and locked tables\n")

    check(
        "everyone reads the stage definitions",
        len(rahul.table("exit_stages").select("code").execute().data),
        10,
    )
    check(
        "employee cannot read the audit log",
        len(subject.table("audit_log").select("id").execute().data),
        0,
    )
    check(
        "employee cannot read the agent approval queue",
        len(subject.table("agent_actions").select("id").execute().data),
        0,
    )

    print("\ndeletion is not a user-facing operation\n")

    check(
        "nobody can delete a case, not even HR (cases are cancelled, not erased)",
        len(priya.table("exit_cases").delete().eq("id", case_id).execute().data),
        0,
    )

    clear_test_cases()

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
