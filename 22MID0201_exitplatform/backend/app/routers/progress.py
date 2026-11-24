"""
Progress across every case the caller can see.

A completion percentage on its own hides the thing HR needs: *where* a case is
stuck. So each row carries a per-stage breakdown, and "blocked" is reported
separately from "not started" — they need different interventions.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter

from app.deps import Actor

router = APIRouter(tags=["progress"])

DONE = ("completed", "waived")
OPEN = ("pending", "in_progress", "blocked")


@router.get("/progress")
async def get_progress(actor: Actor) -> list[dict[str, Any]]:
    db = actor.db

    cases = (
        db.table("exit_cases")
        .select(
            "id, current_stage, resignation_date, last_working_day, status, risk_score,"
            " employee:employees!exit_cases_employee_id_fkey"
            "(id, full_name, emp_code, department, designation, manager_id)"
        )
        # Completed exits are included, not filtered out. Dropping them meant
        # someone who finished vanished from Progress and from the manager's
        # team list on the same day they finished, leaving no sign they had
        # ever exited. They come back at 100% and the UI reads them as done.
        # Cancelled cases stay out: that exit did not happen.
        .in_("status", ["draft", "active", "on_hold", "completed"])
        .order("last_working_day")
        .execute()
    ).data

    if not cases:
        return []

    case_ids = [c["id"] for c in cases]

    stages = (
        db.table("exit_stages").select("code, name, sort_order").order("sort_order").execute()
    ).data

    tasks = (
        db.table("case_tasks")
        .select("case_id, stage_code, status, sla_breached, due_date")
        .in_("case_id", case_ids)
        .execute()
    ).data

    documents = (
        db.table("documents")
        .select("case_id, status")
        .in_("case_id", case_ids)
        .execute()
    ).data

    managers = _manager_names(db, cases)
    today = date.today()
    rows = []

    for case in cases:
        case_tasks = [t for t in tasks if t["case_id"] == case["id"]]
        total = len(case_tasks)
        done = sum(1 for t in case_tasks if t["status"] in DONE)
        blocked = sum(1 for t in case_tasks if t["status"] == "blocked")
        overdue = sum(
            1
            for t in case_tasks
            if t["status"] in OPEN
            and t["due_date"]
            and date.fromisoformat(t["due_date"]) < today
        )

        breakdown = []
        for stage in stages:
            in_stage = [t for t in case_tasks if t["stage_code"] == stage["code"]]
            if not in_stage:
                continue
            stage_done = sum(1 for t in in_stage if t["status"] in DONE)
            breakdown.append(
                {
                    "code": stage["code"],
                    "name": stage["name"],
                    "done": stage_done,
                    "total": len(in_stage),
                    "overdue": sum(
                        1
                        for t in in_stage
                        if t["status"] in OPEN
                        and t["due_date"]
                        and date.fromisoformat(t["due_date"]) < today
                    ),
                    "is_current": stage["code"] == case["current_stage"],
                }
            )

        case_docs = [d for d in documents if d["case_id"] == case["id"]]

        rows.append(
            {
                "case_id": case["id"],
                "employee": case["employee"],
                "manager_name": managers.get(case["employee"].get("manager_id")),
                "current_stage": case["current_stage"],
                "last_working_day": case["last_working_day"],
                "days_remaining": (
                    date.fromisoformat(case["last_working_day"]) - today
                ).days,
                "risk_score": case["risk_score"],
                "tasks_total": total,
                "tasks_done": done,
                "tasks_blocked": blocked,
                "tasks_overdue": overdue,
                "percent_complete": round(done / total * 100) if total else 0,
                "documents_pending": sum(1 for d in case_docs if d["status"] == "pending"),
                "documents_rejected": sum(1 for d in case_docs if d["status"] == "rejected"),
                "stages": breakdown,
            }
        )

    return rows


def _manager_names(db, cases: list[dict]) -> dict[str, str]:
    ids = {c["employee"]["manager_id"] for c in cases if c["employee"].get("manager_id")}
    if not ids:
        return {}
    found = db.table("employees").select("id, full_name").in_("id", list(ids)).execute()
    return {row["id"]: row["full_name"] for row in found.data}
