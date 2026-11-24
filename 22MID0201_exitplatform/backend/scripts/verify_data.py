"""Assert the things that must always be true about the data.

Why this exists
---------------
`verify_rls.py` proves isolation and `verify_api.py` proves the handlers behave.
Neither noticed that eleven cases had tasks marked complete with no documents
behind them — the screen said "24/24 done" and "4 documents still missing" at
the same time, and both were accurately reporting a database that contradicted
itself.

That is the gap this fills. It checks invariants rather than behaviour: facts
that should hold no matter which code path wrote the row. Most of the bugs
found while building this platform were of exactly that shape — two parts each
correct on their own, disagreeing with each other.

Checks are grouped by the bug that motivated them, so a failure points at what
went wrong rather than just what is inconsistent.

Read-only. Run it any time, against any environment.

Usage
-----
    cd backend
    .venv/Scripts/python.exe scripts/verify_data.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import psycopg  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.deps import service_db  # noqa: E402

passed = 0
failed = 0

OPEN_STATES = ("pending", "in_progress", "blocked")
DONE_STATES = ("completed", "waived")


def check(label: str, actual: object, expected: object, hint: str = "") -> None:
    global passed, failed
    if actual == expected:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}")
        print(f"        expected {expected!r}, got {actual!r}")
        if hint:
            print(f"        {hint}")


def main() -> int:
    db = service_db()
    settings = get_settings()

    cases = db.table("exit_cases").select("*").execute().data
    tasks = db.table("case_tasks").select("*").execute().data
    documents = db.table("documents").select("*").execute().data
    employees = {e["id"]: e for e in db.table("employees").select("*").execute().data}
    stages = {s["code"] for s in db.table("exit_stages").select("code").execute().data}
    doc_types = {d["code"] for d in db.table("document_types").select("code").execute().data}

    tasks_by_case: dict[str, list[dict]] = {}
    for t in tasks:
        tasks_by_case.setdefault(t["case_id"], []).append(t)

    # Latest document per (case, type) — a resubmission supersedes the original.
    latest_doc: dict[tuple[str, str], dict] = {}
    for d in sorted(documents, key=lambda x: x["created_at"]):
        latest_doc[(d["case_id"], d["doc_type_code"])] = d

    print("documents and the tasks they satisfy\n")

    # The "24/24 done, 4 documents missing" contradiction.
    done_without_doc = [
        f"{employees[c['employee_id']]['full_name']}: {t['title']}"
        for c in cases
        for t in tasks_by_case.get(c["id"], [])
        if t["doc_type_code"]
        and t["status"] == "completed"
        and (c["id"], t["doc_type_code"]) not in latest_doc
    ]
    check(
        "every completed document-backed task has a document",
        done_without_doc,
        [],
        "Run scripts/seed_case_documents.py, or the task was completed by hand.",
    )

    mismatched = [
        f"{employees[c['employee_id']]['full_name']}: {t['title']} "
        f"(task {t['status']}, document {latest_doc[(c['id'], t['doc_type_code'])]['status']})"
        for c in cases
        for t in tasks_by_case.get(c["id"], [])
        if t["doc_type_code"]
        and (c["id"], t["doc_type_code"]) in latest_doc
        and (
            (t["status"] == "completed")
            != (latest_doc[(c["id"], t["doc_type_code"])]["status"] == "approved")
        )
        and t["status"] != "waived"
    ]
    check(
        "task status agrees with its document",
        mismatched,
        [],
        "Run scripts/backfill_task_document_status.py.",
    )

    # storage_path is UNIQUE; inline documents used to write "" and collided
    # with each other, so only the first inline document in the system worked.
    paths = Counter(d["storage_path"] for d in documents)
    check(
        "no two documents share a storage path",
        [p for p, n in paths.items() if n > 1],
        [],
        "Inline documents need a synthetic unique path, not an empty string.",
    )
    check("no document has an empty storage path", paths.get("", 0), 0)

    print("\ncase structure\n")

    check(
        "every case has a task checklist",
        [
            employees[c["employee_id"]]["full_name"]
            for c in cases
            if not tasks_by_case.get(c["id"])
        ],
        [],
        "create_case() expands task_templates; a case without them is half-created.",
    )
    check(
        "every case sits on a real stage",
        [c["current_stage"] for c in cases if c["current_stage"] not in stages],
        [],
    )
    check(
        "every task sits on a real stage",
        sorted({t["stage_code"] for t in tasks if t["stage_code"] not in stages}),
        [],
    )
    check(
        "every doc_type_code referenced exists",
        sorted(
            {
                t["doc_type_code"]
                for t in tasks
                if t["doc_type_code"] and t["doc_type_code"] not in doc_types
            }
            | {d["doc_type_code"] for d in documents if d["doc_type_code"] not in doc_types}
        ),
        [],
    )
    check(
        "a completed case has no open tasks",
        [
            employees[c["employee_id"]]["full_name"]
            for c in cases
            if c["status"] == "completed"
            and any(t["status"] in OPEN_STATES for t in tasks_by_case.get(c["id"], []))
        ],
        [],
    )
    check(
        "nobody has two open cases",
        [
            name
            for name, n in Counter(
                employees[c["employee_id"]]["full_name"]
                for c in cases
                if c["status"] in ("draft", "active", "on_hold")
            ).items()
            if n > 1
        ],
        [],
        "exit_cases_one_open_per_employee should make this impossible.",
    )

    print("\npeople and sign-in\n")

    check(
        "every employee is linked to a login",
        [e["full_name"] for e in employees.values() if not e["auth_user_id"]],
        [],
    )
    check(
        "every exiting employee has a manager",
        [
            employees[c["employee_id"]]["full_name"]
            for c in cases
            if not employees[c["employee_id"]].get("manager_id")
        ],
        [],
        "Their manager cannot see the case without one.",
    )
    check(
        "every manager_id points at somebody",
        [
            e["full_name"]
            for e in employees.values()
            if e.get("manager_id") and e["manager_id"] not in employees
        ],
        [],
    )

    print("\nagent runs\n")

    runs = db.table("agent_runs").select("id, worker_history").limit(500).execute().data
    check(
        "worker_history is stored as a list, not a JSON string",
        [r["id"][:8] for r in runs if not isinstance(r["worker_history"], list)],
        [],
        "Pass the list to PostgREST; json.dumps() stores a quoted string.",
    )

    print("\nlive updates\n")

    # Realtime silently emitted nothing because the publication was empty.
    expected_live = {
        "notifications",
        "documents",
        "case_tasks",
        "exit_cases",
        "approvals",
        "kt_records",
        "kt_items",
        "agent_actions",
        "case_assets",
        "case_access",
        "case_settlement",
    }
    with psycopg.connect(settings.database_url) as conn:
        published = {
            row[0]
            for row in conn.execute(
                "select tablename from pg_publication_tables "
                "where pubname = 'supabase_realtime' and schemaname = 'public'"
            ).fetchall()
        }
    check(
        "every table the dashboards watch is published to Realtime",
        sorted(expected_live - published),
        [],
        "Without this, subscriptions connect fine and receive nothing.",
    )

    # Every case carries its clearance detail.
    #
    # The asset, access and settlement lists are built by
    # services/clearance.open_clearance_detail, which only runs inside
    # create_case(). A case inserted any other way — the SQL seed does exactly
    # that — arrives with all three empty, and then IT's queue shows the person
    # with nothing to return and Finance has no settlement to work through.
    # Nothing errors; the screens are just blank, which reads as "done".
    missing = []
    for table in ("case_assets", "case_access", "case_settlement"):
        have = {
            row["case_id"]
            for row in db.table(table).select("case_id").execute().data
        }
        missing += [
            f"{employees[c['employee_id']]['full_name']} has no {table[5:]}"
            for c in cases
            if c["status"] != "cancelled" and c["id"] not in have
        ]
    check(
        "every live case has its assets, access and settlement built",
        sorted(missing),
        [],
        "Rebuild with services.clearance.open_clearance_detail(case_id, employee).",
    )

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
