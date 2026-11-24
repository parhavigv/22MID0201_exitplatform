"""
"Needs you" — everything awaiting the signed-in person's action, across every
case they can see.

Without this a manager has to open each report's case in turn to discover there
is nothing to do. RLS already scopes what they can see, so this endpoint is
pure aggregation: no extra permission logic, and a manager physically cannot
receive an item for someone else's report.

Three kinds of item:
  document  a document uploaded and waiting for review
  stage     a stage whose work is finished and which needs sign-off
  overdue   a task past its due date that the actor owns or oversees
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter

from app.deps import Actor

router = APIRouter(tags=["inbox"])

OPEN = ("pending", "in_progress", "blocked")

# Which task owners each app role is responsible for chasing. IT, Finance and
# Admin have no dashboard in v1, so HR covers them.
CHASED_BY: dict[str, set[str]] = {
    "manager": {"employee", "manager"},
    "hr": {"employee", "manager", "hr", "it", "finance", "admin"},
    "employee": set(),
}


@router.get("/inbox")
async def get_inbox(actor: Actor) -> dict[str, Any]:
    db = actor.db

    cases = (
        db.table("exit_cases")
        .select(
            "id, current_stage, last_working_day, status,"
            " employee:employees!exit_cases_employee_id_fkey(id, full_name, department)"
        )
        .in_("status", ["draft", "active", "on_hold"])
        .execute()
    )

    if not cases.data:
        return {"documents": [], "stages": [], "overdue": [], "total": 0}

    case_ids = [c["id"] for c in cases.data]
    by_id = {c["id"]: c for c in cases.data}

    stage_names = {
        s["code"]: s["name"]
        for s in db.table("exit_stages").select("code, name").execute().data
    }
    doc_names = {
        d["code"]: d["name"]
        for d in db.table("document_types").select("code, name").execute().data
    }

    tasks = (
        db.table("case_tasks")
        .select("id, case_id, stage_code, title, owner_role, status, due_date, sla_breached")
        .in_("case_id", case_ids)
        .execute()
    ).data

    documents = (
        db.table("documents")
        .select(
            "id, case_id, doc_type_code, file_name, uploaded_by, created_at,"
            " verification, is_inline, content"
        )
        .in_("case_id", case_ids)
        .eq("status", "pending")
        .order("created_at")
        .execute()
    ).data

    # --- documents awaiting review -----------------------------------------
    # You cannot review your own upload (enforced in documents.py), so those
    # are filtered out here rather than shown and then refused.
    pending_documents = [
        {
            "document_id": d["id"],
            "case_id": d["case_id"],
            "employee": by_id[d["case_id"]]["employee"],
            "document_name": doc_names.get(d["doc_type_code"], d["doc_type_code"]),
            "file_name": d["file_name"],
            "uploaded_at": d["created_at"],
            # Carried into the queue so a flagged file is obvious before the
            # reviewer opens it — that is the moment the warning is useful.
            "verification": d.get("verification"),
            # An inline submission — a signed NDA, a KT summary — has no file
            # to open, so its text has to travel with the queue row or there
            # is nothing to review. These two were missing, which meant the
            # preview in Needs You rendered empty and managers were approving
            # NDAs they could not read.
            "is_inline": d.get("is_inline", False),
            "content": d.get("content"),
        }
        for d in documents
        if d["uploaded_by"] != actor.employee_id
    ]

    # --- stages ready to sign off ------------------------------------------
    ready_stages = []
    unreviewed_by_case: dict[str, int] = {}
    for d in documents:
        unreviewed_by_case[d["case_id"]] = unreviewed_by_case.get(d["case_id"], 0) + 1

    for case in cases.data:
        if actor.role == "employee":
            break  # the exiting employee never signs off their own case

        stage = case["current_stage"]
        open_in_stage = [
            t
            for t in tasks
            if t["case_id"] == case["id"]
            and t["stage_code"] == stage
            and t["status"] in OPEN
        ]
        if open_in_stage or unreviewed_by_case.get(case["id"]):
            continue

        ready_stages.append(
            {
                "case_id": case["id"],
                "employee": case["employee"],
                "stage_code": stage,
                "stage_name": stage_names.get(stage, stage),
                "last_working_day": case["last_working_day"],
            }
        )

    # --- overdue tasks ------------------------------------------------------
    today = date.today()
    chased = CHASED_BY.get(actor.role, set())
    overdue = []

    for t in tasks:
        if t["status"] not in OPEN or not t["due_date"]:
            continue
        due = date.fromisoformat(t["due_date"])
        if due >= today:
            continue

        mine = t["owner_role"] == "employee" and actor.role == "employee"
        if not mine and t["owner_role"] not in chased:
            continue

        overdue.append(
            {
                "task_id": t["id"],
                "case_id": t["case_id"],
                "employee": by_id[t["case_id"]]["employee"],
                "title": t["title"],
                "owner_role": t["owner_role"],
                "stage_name": stage_names.get(t["stage_code"], t["stage_code"]),
                "due_date": t["due_date"],
                "days_overdue": (today - due).days,
            }
        )

    overdue.sort(key=lambda o: -o["days_overdue"])

    return {
        "documents": pending_documents,
        "stages": ready_stages,
        "overdue": overdue,
        "total": len(pending_documents) + len(ready_stages) + len(overdue),
    }
