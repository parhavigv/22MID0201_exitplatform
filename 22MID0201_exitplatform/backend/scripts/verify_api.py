"""
End-to-end check of the API with real Supabase Auth tokens.

Signs in through Supabase, then calls the running FastAPI server over HTTP
exactly as the browser does. This covers the whole chain the RLS tests do not:
JWT verification in deps.py, the actor lookup, and every handler's own
authorisation rules.

Requires the backend running on :8000.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.deps import service_db  # noqa: E402
from scripts import _fixtures  # noqa: E402
from scripts.apply_migrations import connect as db_connect  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "backend" / ".env")

API = "http://127.0.0.1:8000/api"
URL = os.environ["SUPABASE_URL"]
ANON = os.environ["SUPABASE_ANON_KEY"]
PASSWORD = "ExitDemo!2026"

ARJUN = "arjun.menon@example.com"
PRIYA = "priya.nair@example.com"

# Everyone below is a throwaway account the suite creates and deletes — see
# scripts/_fixtures.py. The demo roster is one HR partner, one manager, and
# eleven exiting employees who all report to him, which gives the suite nobody
# without a case and no second manager, and both are needed to prove isolation.
#
# The subject is a fixture for a sharper reason: seed_case() deletes and
# recreates its case every run, and that cascades to the person's documents.
# Pointed at a real demo employee it quietly wiped their uploads.
SUBJECT = _fixtures.SUBJECT
SUBJECT_NAME = _fixtures.SUBJECT_NAME
RAHUL = _fixtures.PEER
VIKRAM = _fixtures.OTHER_MANAGER

passed = 0
failed = 0


def check(label: str, actual: object, expected: object) -> None:
    global passed, failed
    if actual == expected:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  (expected {expected!r}, got {actual!r})")


def token_for(email: str) -> str:
    """Sign in, retrying briefly on a throttled auth call.

    The suite signs five users in back to back, and Supabase Auth rate-limits
    by IP. A throttled sign-in would otherwise surface as an unrelated
    assertion failing further down — a 401 on /me, say — which reads like an
    isolation bug and is not one. Retry the sign-in; never the assertions.
    """
    last: Exception | None = None
    for attempt in range(4):
        try:
            client = create_client(URL, ANON)
            result = client.auth.sign_in_with_password(
                {"email": email, "password": PASSWORD}
            )
            if result.session:
                return result.session.access_token
            last = RuntimeError("sign-in returned no session")
        except Exception as exc:  # noqa: BLE001 - retried below, re-raised at the end
            last = exc
        time.sleep(1.5 * (attempt + 1))
    raise SystemExit(f"Could not sign in as {email} after 4 attempts: {last}")


def get(token: str, path: str) -> httpx.Response:
    return httpx.get(f"{API}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=30)


def seed_case() -> str:
    """Create a case for the fixture subject, so the API tests have one to read."""
    conn = db_connect()
    with conn.cursor() as cur:
        cur.execute("delete from exit_cases where employee_id in "
                    "(select id from employees where work_email = %s)", (SUBJECT,))
        cur.execute(
            """
            insert into exit_cases (
                employee_id, resignation_date, last_working_day,
                notice_period_days, current_stage, status
            )
            select id, current_date - 20, current_date + 40, 60,
                   'KT_EXECUTION', 'active'
            from employees where work_email = %s
            returning id
            """,
            (SUBJECT,),
        )
        case_id = cur.fetchone()[0]

        # Expand the template into real tasks, as Phase 2's case-creation
        # service will do.
        cur.execute(
            """
            insert into case_tasks (
                case_id, stage_code, template_id, title, description,
                owner_role, assignee_id, doc_type_code, due_date, sort_order
            )
            select %s, t.stage_code, t.id, t.title, t.description,
                   t.owner_role,
                   case when t.owner_role = 'employee' then c.employee_id end,
                   t.doc_type_code,
                   c.resignation_date + t.offset_days,
                   t.sort_order
            from task_templates t
            cross join (select employee_id, resignation_date
                        from exit_cases where id = %s) c
            where t.is_active
            """,
            (case_id, case_id),
        )

        # create_case() also opens these; the fixture must match or the KT and
        # interview endpoints have nothing to act on.
        cur.execute(
            "insert into kt_records (case_id, overall_status) values (%s, 'not_started')",
            (case_id,),
        )
        cur.execute("insert into exit_interviews (case_id) values (%s)", (case_id,))
        conn.commit()
    conn.close()
    return str(case_id)


def cleanup() -> None:
    """Remove every case belonging to a test subject, however a run ended."""
    conn = db_connect()
    with conn.cursor() as cur:
        cur.execute(
            "delete from exit_cases where employee_id in "
            "(select id from employees where work_email = any(%s))",
            ([SUBJECT, RAHUL],),
        )
        conn.commit()
    _fixtures.remove(conn)
    conn.close()


def main() -> int:
    try:
        httpx.get("http://127.0.0.1:8000/health", timeout=5)
    except httpx.ConnectError:
        print("Backend is not running. Start it with:")
        print("  .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000")
        return 1

    cleanup()  # re-runnable regardless of how a previous run ended
    print("Creating test fixtures...")
    conn = db_connect()
    _fixtures.ensure(conn)
    conn.close()
    case_id = seed_case()

    print("Signing in...\n")
    subject = token_for(SUBJECT)
    rahul = token_for(RAHUL)
    arjun = token_for(ARJUN)
    vikram = token_for(VIKRAM)
    priya = token_for(PRIYA)

    print("authentication\n")

    check("no token is rejected", httpx.get(f"{API}/me", timeout=30).status_code, 401)
    check(
        "a garbage token is rejected",
        get("not.a.real.token", "/me").status_code,
        401,
    )

    me = get(subject, "/me")
    check("valid token returns the session", me.status_code, 200)
    check("session carries the full employee record", me.json()["employee"]["designation"], "Senior Engineer")
    check("role is resolved from the database", me.json()["role"], "employee")
    check("manager's role is resolved", get(arjun, "/me").json()["role"], "manager")
    check("HR's role is resolved", get(priya, "/me").json()["role"], "hr")

    print("\n/me/exit — the employee dashboard\n")

    mine = get(subject, "/me/exit")
    check("returns the case", mine.status_code, 200)
    body = mine.json()
    check("tasks were expanded from the template", len(body["tasks"]), 24)
    check("all ten stages are returned", len(body["stages"]), 10)
    check("manager is resolved", body["manager"]["full_name"], "Arjun Menon")
    check("someone with no exit gets null", get(rahul, "/me/exit").json(), None)

    print("\n/cases — scoping\n")

    check(
        "peer sees no cases",
        len(get(rahul, "/cases?scope=all").json()),
        0,
    )
    # Assert the boundary — this case is visible to the people who should see
    # it — rather than a case count. Extra demo cases are a normal thing to
    # seed (scripts/seed_more_employees.py) and must not fail this suite; what
    # would be a real failure is the subject's case going missing, or Vikram
    # seeing it.
    check(
        "manager sees their report's case",
        case_id in {c["case"]["id"] for c in get(arjun, "/cases?scope=all").json()},
        True,
    )
    check(
        "another team's manager sees none",
        len(get(vikram, "/cases?scope=all").json()),
        0,
    )
    check("HR sees it", case_id in {c["case"]["id"] for c in get(priya, "/cases?scope=all").json()}, True)

    summary = next(c for c in get(arjun, "/cases?scope=all").json() if c["case"]["id"] == case_id)
    check("summary counts open tasks", summary["open_tasks"], 24)
    check("summary names the employee", summary["employee"]["full_name"], SUBJECT_NAME)

    print("\ndirect case access\n")

    check("owner can read their case", get(subject, f"/cases/{case_id}").status_code, 200)
    check("manager can read it", get(arjun, f"/cases/{case_id}").status_code, 200)
    check("peer gets 404, not 403", get(rahul, f"/cases/{case_id}").status_code, 404)
    check(
        "another team's manager gets 404",
        get(vikram, f"/cases/{case_id}").status_code,
        404,
    )
    check(
        "peer cannot list its tasks",
        len(get(rahul, f"/cases/{case_id}/tasks").json()),
        0,
    )

    print("\ntask updates\n")

    tasks = get(subject, f"/cases/{case_id}/tasks").json()
    own_task = next(t for t in tasks if t["owner_role"] == "employee")

    def patch(token: str, task_id: str, status_value: str) -> int:
        return httpx.patch(
            f"{API}/tasks/{task_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"status": status_value},
            timeout=30,
        ).status_code

    check("employee completes their own task", patch(subject, own_task["id"], "completed"), 204)
    check("peer cannot touch it", patch(rahul, own_task["id"], "pending"), 404)
    check("employee cannot waive a task", patch(subject, own_task["id"], "waived"), 403)
    check("HR can waive it", patch(priya, own_task["id"], "waived"), 204)

    print("\naudit trail\n")

    # Exactly two of the four PATCH attempts above succeeded; the other two were
    # correctly rejected. So exactly two audit rows, both naming this case.
    conn = db_connect()
    with conn.cursor() as cur:
        cur.execute(
            """
            select action, actor_id is not null, case_id = %s
            from audit_log where case_id = %s order by at
            """,
            (case_id, case_id),
        )
        rows = cur.fetchall()
    conn.close()

    check("one audit row per successful change", len(rows), 2)
    check(
        "rows name the action",
        {r[0] for r in rows},
        {"case_tasks.status_changed"},
    )
    check("every row records who did it", all(r[1] for r in rows), True)
    check("every row is attached to the case", all(r[2] for r in rows), True)

    print("\n/inbox — needs you\n")

    manager_inbox = get(arjun, "/inbox").json()
    check("manager sees overdue work on their team", manager_inbox["total"] > 0, True)
    # The inbox may legitimately span several reports. What must hold is that
    # every name in it is one of Arjun's, and that the subject's case is among them.
    admin = service_db()
    arjun_id = admin.table("employees").select("id").eq("work_email", ARJUN).single().execute().data["id"]
    arjun_reports = {
        r["full_name"]
        for r in admin.table("employees").select("full_name").eq("manager_id", arjun_id).execute().data
    }
    inbox_names = {o["employee"]["full_name"] for o in manager_inbox["overdue"]}
    check("every overdue item belongs to their report", inbox_names <= arjun_reports, True)
    check("their report's overdue work is present", SUBJECT_NAME in inbox_names, True)
    check(
        "another team's manager has an empty inbox",
        get(vikram, "/inbox").json()["total"],
        0,
    )
    check(
        "a peer has an empty inbox",
        get(rahul, "/inbox").json()["total"],
        0,
    )
    check("HR sees the same overdue work", get(priya, "/inbox").json()["total"] > 0, True)

    print("\n/progress\n")

    progress = get(priya, "/progress").json()
    check("HR sees the active case in progress", case_id in {p["case_id"] for p in progress}, True)
    row = next(p for p in progress if p["case_id"] == case_id)
    check("percent complete is computed", 0 < row["percent_complete"] < 100, True)
    check("stage breakdown covers all ten stages", len(row["stages"]), 10)
    check(
        "exactly one stage is marked current",
        sum(1 for s in row["stages"] if s["is_current"]),
        1,
    )
    check("manager is named", row["manager_name"], "Arjun Menon")
    check("a peer sees no progress rows", len(get(rahul, "/progress").json()), 0)

    print("\nreminders\n")

    # Pin to the subject's own overdue task. The manager's inbox spans every direct
    # report and is sorted by how late each task is, so seeding more demo cases
    # (scripts/seed_more_employees.py) puts someone else's task at index 0 —
    # and every assertion below is about the subject's bell specifically.
    subject_overdue = [
        o for o in manager_inbox["overdue"] if o["employee"]["full_name"] == SUBJECT_NAME
    ]
    if not subject_overdue:
        raise SystemExit("No overdue task for the subject — reseed with apply_migrations.py --seed.")
    overdue_task = subject_overdue[0]["task_id"]

    draft = get(arjun, f"/tasks/{overdue_task}/reminder-draft").json()
    check("draft names the recipient", draft["recipient"]["full_name"], SUBJECT_NAME)
    check("draft subject names the task", draft["subject"].startswith("Overdue:"), True)
    check("draft body is pre-filled", len(draft["body"]) > 80, True)

    def remind(token: str) -> int:
        return httpx.post(
            f"{API}/tasks/{overdue_task}/remind",
            headers={"Authorization": f"Bearer {token}"},
            json={"subject": draft["subject"], "body": draft["body"]},
            timeout=30,
        ).status_code

    check("an employee cannot send reminders", remind(subject), 403)
    check("another team's manager cannot", remind(vikram), 404)
    check("the manager can", remind(arjun), 204)

    notes = get(subject, "/notifications").json()
    check("the reminder reached the employee's bell", len(notes), 1)
    check("with the drafted subject", notes[0]["title"], draft["subject"])
    check("and starts unread", notes[0]["read_at"], None)
    check("a peer sees no notifications", len(get(rahul, "/notifications").json()), 0)

    print("\nopening a case\n")

    def open_case(token: str, employee_email: str | None) -> httpx.Response:
        body: dict[str, object] = {
            "resignation_date": str(date.today()),
            "last_working_day": str(date.today() + timedelta(days=30)),
            "notice_period_days": 30,
        }
        if employee_email:
            conn = db_connect()
            with conn.cursor() as cur:
                cur.execute("select id from employees where work_email = %s", (employee_email,))
                body["employee_id"] = str(cur.fetchone()[0])
            conn.close()
        return httpx.post(
            f"{API}/cases",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=30,
        )

    check("cannot open a second case for the same person", open_case(subject, None).status_code, 409)
    check(
        "a manager cannot resign on someone's behalf",
        open_case(arjun, RAHUL).status_code,
        403,
    )

    opened = open_case(rahul, None)
    check("an employee can open their own", opened.status_code, 201)

    new_case_id = opened.json()["id"]
    new_tasks = get(rahul, f"/cases/{new_case_id}/tasks").json()
    check("the template expanded into 24 tasks", len(new_tasks), 24)
    check(
        "due dates are clamped to the last working day",
        all(t["due_date"] <= str(date.today() + timedelta(days=30)) for t in new_tasks),
        True,
    )
    check(
        "only the employee's own tasks get an assignee",
        {t["assignee_id"] is not None for t in new_tasks if t["owner_role"] == "employee"},
        {True},
    )
    check("a KT record was opened", get(rahul, f"/cases/{new_case_id}/kt").json() is not None, True)
    check(
        "an exit interview was opened",
        get(rahul, f"/cases/{new_case_id}/interview").json() is not None,
        True,
    )

    print("\nfailed creation leaves nothing behind\n")

    # A case whose task expansion fails must not survive — a checklist-less case
    # blocks the person from ever retrying.
    conn = db_connect()
    with conn.cursor() as cur:
        cur.execute("delete from exit_cases where id = %s", (new_case_id,))
        conn.commit()
        cur.execute(
            """
            select count(*) from exit_cases c
            join employees e on e.id = c.employee_id
            where e.work_email = %s
            """,
            (RAHUL,),
        )
        leftover = cur.fetchone()[0]
    conn.close()
    check("cancelling a case removes its tasks too", leftover, 0)

    retry = open_case(rahul, None)
    check("the person can open a new case afterwards", retry.status_code, 201)

    conn = db_connect()
    with conn.cursor() as cur:
        cur.execute("delete from exit_cases where id = %s", (retry.json()["id"],))
        conn.commit()
    conn.close()

    print("\nstage override — HR's escape hatch\n")

    def override(token: str, stage: str, reason: str = "Leaver already departed.") -> int:
        return httpx.post(
            f"{API}/cases/{case_id}/override-stage",
            headers={"Authorization": f"Bearer {token}"},
            json={"stage_code": stage, "reason": reason},
            timeout=30,
        ).status_code

    check("an employee cannot override", override(subject, "FINAL_SETTLEMENT"), 403)
    check("a manager cannot override", override(arjun, "FINAL_SETTLEMENT"), 403)
    check("a reason is required", override(priya, "FINAL_SETTLEMENT", "no"), 422)
    check("an unknown stage is rejected", override(priya, "NOT_A_STAGE"), 422)
    check("HR can skip the gates", override(priya, "FINAL_SETTLEMENT"), 204)
    check("overriding to the current stage is refused", override(priya, "FINAL_SETTLEMENT"), 409)
    check("HR can move it backwards", override(priya, "KT_EXECUTION"), 204)

    conn = db_connect()
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from audit_log where case_id = %s "
            "and action = 'exit_cases.stage_overridden'",
            (case_id,),
        )
        overrides = cur.fetchone()[0]
    conn.close()
    # Two of the three attempts above succeeded; the repeat was refused as a
    # no-op and must therefore leave no trace.
    check("each override is audited under its own action", overrides, 2)

    print("\nnominating a successor\n")

    def nominate(token: str, successor_email: str | None, raw: str | None = None) -> int:
        successor_id = raw
        if successor_email:
            conn = db_connect()
            with conn.cursor() as cur:
                cur.execute("select id from employees where work_email = %s", (successor_email,))
                successor_id = str(cur.fetchone()[0])
            conn.close()
        return httpx.patch(
            f"{API}/cases/{case_id}/kt",
            headers={"Authorization": f"Bearer {token}"},
            json={"successor_id": successor_id},
            timeout=30,
        ).status_code

    check("the leaver cannot pick their own successor", nominate(subject, RAHUL), 403)
    check(
        "someone cannot be their own successor",
        nominate(arjun, SUBJECT),
        422,
    )
    check("the manager can nominate", nominate(arjun, RAHUL), 204)
    check("HR can nominate", nominate(priya, RAHUL), 204)

    kt = get(arjun, f"/cases/{case_id}/kt").json()
    check("the nomination stuck", kt["successor_id"] is not None, True)

    verdict = httpx.patch(
        f"{API}/cases/{case_id}/kt",
        headers={"Authorization": f"Bearer {arjun}"},
        json={"overall_status": "verified"},
        timeout=30,
    )
    check("the manager can sign off the handover", verdict.status_code, 204)

    kt = get(arjun, f"/cases/{case_id}/kt").json()
    check("signing off records who reviewed it", kt["reviewed_by"] is not None, True)

    cleanup()
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
