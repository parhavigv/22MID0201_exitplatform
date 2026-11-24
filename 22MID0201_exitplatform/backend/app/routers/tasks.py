"""Task status changes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.deps import Actor
from app.services.audit import write_audit
from app.services.documents import is_outbound

router = APIRouter(tags=["tasks"])

TaskStatus = Literal["pending", "in_progress", "blocked", "completed", "waived"]

# Only HR may waive a task — it clears an obligation rather than fulfilling it.
RESTRICTED: set[str] = {"waived"}


class TaskPatch(BaseModel):
    status: TaskStatus


@router.patch("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_task(task_id: str, patch: TaskPatch, actor: Actor) -> None:
    db = actor.db

    existing = db.table("case_tasks").select("*").eq("id", task_id).execute()
    if not existing.data:
        # RLS may have filtered it; do not distinguish that from a bad id.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found.")

    before = existing.data[0]

    if patch.status in RESTRICTED and not actor.is_hr:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only HR can waive a task."
        )

    # A task that owes the employee a document cannot be closed by declaring
    # it closed. "Issue relieving letter" marked done with nothing issued
    # leaves the employee permanently without their letter, and the case
    # completes around the gap — which is exactly what happened on a real
    # case here before this check existed.
    #
    # Waiving is still allowed: that is HR deciding the document is not owed
    # at all, which is a different statement from pretending it was sent.
    if patch.status == "completed" and before.get("doc_type_code"):
        if is_outbound(before["doc_type_code"]):
            issued = (
                db.table("documents")
                .select("id")
                .eq("case_id", before["case_id"])
                .eq("doc_type_code", before["doc_type_code"])
                .eq("status", "approved")
                .limit(1)
                .execute()
            )
            if not issued.data:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Issue the document to complete this task — the employee is"
                    " owed it. Generate it, or upload your own file.",
                )

    now = datetime.now(timezone.utc).isoformat()
    changes: dict[str, object] = {"status": patch.status}

    if patch.status == "completed":
        changes["completed_at"] = now
        changes["completed_by"] = actor.employee_id
        # Completing late still clears the breach — the delay lives in audit_log.
        changes["sla_breached"] = False
    else:
        changes["completed_at"] = None
        changes["completed_by"] = None

    result = db.table("case_tasks").update(changes).eq("id", task_id).execute()
    if not result.data:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You cannot change this task."
        )

    write_audit(
        action="case_tasks.status_changed",
        entity_table="case_tasks",
        entity_id=task_id,
        actor=actor,
        case_id=before["case_id"],
        before={"status": before["status"]},
        after={"status": patch.status},
    )
