"""Give every seeded case the documents its finished tasks imply.

The inconsistency this fixes
----------------------------
`seed_more_employees.py` marked tasks complete based on how far through the
workflow each case had got, but never created the documents those tasks are
about. The result read as a contradiction on screen: a case showing 24/24 tasks
done, whose Documents page still said "4 required documents are still missing".

Nothing was wrong with the application — it reported exactly what the database
held. The seed data was the lie.

What this does
--------------
For every document-backed task, create the document that task is about, with a
status that agrees with the task:

    task completed    ->  document approved  (reviewed by the manager)
    task in_progress  ->  document pending   (submitted, awaiting review)
    anything else     ->  no document        (nothing has been submitted yet)

Real PDF bytes are uploaded to Supabase Storage from the sample pack, so the
download link works rather than 404ing on an empty path. NDA_ACKNOWLEDGEMENT is
filled in inside the app (migration 0007), so it is written as an inline
document with form content instead of a file.

Re-runnable: a case that already has a document of that type is left alone.

Prerequisites
-------------
The sample PDFs must exist. Generate them first if needed:

    .venv/Scripts/python.exe scripts/make_sample_documents.py

Usage
-----
    cd backend
    .venv/Scripts/python.exe scripts/seed_case_documents.py --dry-run
    .venv/Scripts/python.exe scripts/seed_case_documents.py
    .venv/Scripts/python.exe scripts/seed_case_documents.py --undo
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.deps import service_db  # noqa: E402

BUCKET = "case-documents"
SAMPLES = Path.home() / "Desktop" / "Exit Platform Sample Documents"

# Which sample file stands in for each document type. NDA is absent on purpose:
# it is a form, not a file.
SAMPLE_FOR = {
    "RESIGNATION_LETTER": "Resignation Letter.pdf",
    "KT_DOCUMENT": "Knowledge Transfer Document.pdf",
    "ASSET_RETURN_FORM": "Asset Return Form.pdf",
    "NO_DUES_FINANCE": "Finance No-Dues Certificate.pdf",
    "FINAL_SETTLEMENT_STATEMENT": "Full and Final Settlement Statement.pdf",
    "RELIEVING_LETTER": "Relieving Letter.pdf",
    "EXPERIENCE_LETTER": "Experience Letter.pdf",
}

INLINE_NDA_CONTENT = {
    "acknowledgements": [True, True, True, True],
    "submitted_at": "2026-09-01T00:00:00Z",
}

STATUS_FOR_TASK = {"completed": "approved", "in_progress": "pending"}


def _upload(storage_path: str, data: bytes) -> None:
    """Put the bytes in the bucket, tolerating a path that is already there."""
    try:
        service_db().storage.from_(BUCKET).upload(
            storage_path, data, {"content-type": "application/pdf"}
        )
    except Exception as exc:  # noqa: BLE001 - duplicate is fine, anything else is not
        if "exists" not in str(exc).lower() and "duplicate" not in str(exc).lower():
            raise


def seed(dry_run: bool) -> int:
    db = service_db()

    missing = [f for f in SAMPLE_FOR.values() if not (SAMPLES / f).exists()]
    if missing and not dry_run:
        print("Sample PDFs are missing — run scripts/make_sample_documents.py first:")
        for f in missing:
            print(f"   {f}")
        return 1

    employees = {e["id"]: e for e in db.table("employees").select("*").execute().data}
    cases = db.table("exit_cases").select("id, employee_id").execute().data

    created = 0
    for case in cases:
        employee = employees[case["employee_id"]]
        manager_id = employee.get("manager_id")

        existing = {
            d["doc_type_code"]
            for d in db.table("documents")
            .select("doc_type_code")
            .eq("case_id", case["id"])
            .execute()
            .data
        }

        tasks = (
            db.table("case_tasks")
            .select("doc_type_code, status, completed_at")
            .eq("case_id", case["id"])
            .not_.is_("doc_type_code", "null")
            .execute()
        ).data

        for task in tasks:
            code = task["doc_type_code"]
            doc_status = STATUS_FOR_TASK.get(task["status"])
            if not doc_status or code in existing:
                continue

            existing.add(code)
            created += 1
            print(f"  {employee['full_name']:<18}{code:<28}{doc_status}")
            if dry_run:
                continue

            reviewed = doc_status == "approved"
            row: dict[str, object] = {
                "case_id": case["id"],
                "doc_type_code": code,
                "uploaded_by": employee["id"],
                "status": doc_status,
                "reviewed_by": manager_id if reviewed else None,
                "reviewed_at": task["completed_at"] if reviewed else None,
            }

            if code == "NDA_ACKNOWLEDGEMENT":
                content = {**INLINE_NDA_CONTENT, "full_name": employee["full_name"]}
                payload = json.dumps(content, separators=(",", ":"))
                row.update(
                    {
                        "file_name": f"{code}_inline",
                        # storage_path is UNIQUE; an empty string collides with
                        # every other inline document. Same synthetic path the
                        # live endpoint uses.
                        "storage_path": f"inline/{case['id']}/{code}/{uuid.uuid4()}",
                        "mime_type": "application/json",
                        "size_bytes": len(payload.encode("utf-8")),
                        "is_inline": True,
                        "content": content,
                    }
                )
            else:
                sample = SAMPLES / SAMPLE_FOR[code]
                data = sample.read_bytes()
                path = f"{case['id']}/{code}/{uuid.uuid4()}.pdf"
                _upload(path, data)
                row.update(
                    {
                        "file_name": sample.name,
                        "storage_path": path,
                        "mime_type": "application/pdf",
                        "size_bytes": len(data),
                        "is_inline": False,
                    }
                )

            db.table("documents").insert(row).execute()

    if not created:
        print("Nothing to add — every finished task already has its document.")
    elif dry_run:
        print(f"\n{created} document(s) would be created. Re-run without --dry-run.")
    else:
        print(f"\n{created} document(s) created.")
    return 0


def undo() -> int:
    """Remove documents this script created, leaving anything hand-uploaded."""
    db = service_db()
    names = set(SAMPLE_FOR.values())
    removed = 0
    for doc in db.table("documents").select("id, file_name, is_inline").execute().data:
        if doc["file_name"] in names or doc["file_name"] == "NDA_ACKNOWLEDGEMENT_inline":
            db.table("documents").delete().eq("id", doc["id"]).execute()
            removed += 1
    print(f"Removed {removed} seeded document(s).")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report without writing.")
    parser.add_argument("--undo", action="store_true", help="Remove seeded documents.")
    args = parser.parse_args()
    raise SystemExit(undo() if args.undo else seed(args.dry_run))
