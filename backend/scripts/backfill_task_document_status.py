"""Reconcile every document-backed task with the state of its document.

Why this is needed
------------------
Until `app/services/documents.py` existed, approving a document did not touch
the task it satisfied. Every document uploaded or reviewed before that change
therefore left its task stranded — a KT document sitting `approved` while
"Upload knowledge transfer document" still read `in_progress`, and completion
percentages understating reality across every case.

This walks existing data once and applies the same rule the live code now
applies on each document event:

    latest document approved   ->  task completed
    latest document pending    ->  task in_progress
    latest document rejected   ->  task pending
    no document at all         ->  left alone

Waived tasks are never touched: HR decided the obligation did not apply.

Safe to re-run — it only writes where the task disagrees with its document, so
a second run reports nothing to do. Use --dry-run to see what it would change.

Usage
-----
    cd backend
    .venv/Scripts/python.exe scripts/backfill_task_document_status.py --dry-run
    .venv/Scripts/python.exe scripts/backfill_task_document_status.py
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.deps import service_db  # noqa: E402

TASK_STATUS_FOR_DOCUMENT = {
    "approved": "completed",
    "pending": "in_progress",
    "rejected": "pending",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report without writing.")
    args = parser.parse_args()

    db = service_db()
    employees = {e["id"]: e["full_name"] for e in db.table("employees").select("id, full_name").execute().data}
    cases = db.table("exit_cases").select("id, employee_id").execute().data

    changed = 0
    for case in cases:
        who = employees.get(case["employee_id"], "?")

        documents = (
            db.table("documents")
            .select("doc_type_code, status, created_at")
            .eq("case_id", case["id"])
            .order("created_at")
            .execute()
        ).data
        if not documents:
            continue

        # Later uploads supersede earlier ones for the same type.
        latest: dict[str, str] = {}
        for doc in documents:
            latest[doc["doc_type_code"]] = doc["status"]

        tasks = (
            db.table("case_tasks")
            .select("id, title, status, doc_type_code")
            .eq("case_id", case["id"])
            .not_.is_("doc_type_code", "null")
            .execute()
        ).data

        for task in tasks:
            doc_status = latest.get(task["doc_type_code"])
            if doc_status is None or task["status"] == "waived":
                continue

            want = TASK_STATUS_FOR_DOCUMENT.get(doc_status)
            if not want or task["status"] == want:
                continue

            print(f"  {who:<18}{task['title'][:38]:<40}{task['status']:>12} -> {want}")
            changed += 1

            if not args.dry_run:
                update: dict[str, object] = {"status": want}
                if want == "completed":
                    update["completed_at"] = datetime.now(timezone.utc).isoformat()
                    update["sla_breached"] = False
                else:
                    update["completed_at"] = None
                    update["completed_by"] = None
                db.table("case_tasks").update(update).eq("id", task["id"]).execute()

    if not changed:
        print("Nothing to reconcile — every document-backed task already matches its document.")
    elif args.dry_run:
        print(f"\n{changed} task(s) would change. Re-run without --dry-run to apply.")
    else:
        print(f"\n{changed} task(s) reconciled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
