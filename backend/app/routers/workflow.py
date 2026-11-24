"""
Stage sign-off, knowledge transfer, and the exit interview.

The stage machine is deliberately dumb: stages advance one at a time, in the
seeded order, and only when nothing in the current stage is outstanding. There
is no skipping. HR can override by editing the case directly, and that override
lands in the audit log like everything else.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.deps import Actor
from app.services.audit import write_audit

router = APIRouter(tags=["workflow"])

OPEN_TASK_STATES = ("pending", "in_progress", "blocked")


class StageDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str | None = None


class StageOverride(BaseModel):
    stage_code: str
    reason: str = Field(min_length=3, max_length=500)


class KtRecordPatch(BaseModel):
    successor_id: str | None = None
    overall_status: Literal[
        "not_started", "in_progress", "documented", "verified", "gap"
    ] | None = None


class KtItemPatch(BaseModel):
    coverage_status: Literal[
        "not_started", "in_progress", "documented", "verified", "gap"
    ] | None = None
    detail: str | None = None
    gap_note: str | None = None


class KtItemCreate(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    detail: str = ""


class InterviewBody(BaseModel):
    responses: dict[str, str | int]
    submit: bool = False


# ---------------------------------------------------------------------------
# Stage sign-off
# ---------------------------------------------------------------------------


@router.post(
    "/cases/{case_id}/stages/{stage_code}/decide",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def decide_stage(
    case_id: str, stage_code: str, body: StageDecision, actor: Actor
) -> None:
    db = actor.db

    found = db.table("exit_cases").select("*").eq("id", case_id).execute()
    if not found.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")
    exit_case = found.data[0]

    if exit_case["current_stage"] != stage_code:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This case is at {exit_case['current_stage']}, not {stage_code}. "
            "Someone else may have moved it — reload and try again.",
        )

    if body.decision == "approved":
        outstanding = (
            db.table("case_tasks")
            .select("id", count="exact")
            .eq("case_id", case_id)
            .eq("stage_code", stage_code)
            .in_("status", list(OPEN_TASK_STATES))
            .execute()
        )
        if outstanding.count:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{outstanding.count} task(s) in this stage are still open.",
            )

        # Only documents belonging to *this* stage block it. The check used to
        # span the whole case, so a document uploaded early for a later stage
        # held up every sign-off before it. Stage membership comes from the
        # document type, the same way tasks carry their stage_code.
        stage_doc_types = [
            d["code"]
            for d in db.table("document_types")
            .select("code")
            .eq("stage_code", stage_code)
            .execute()
            .data
        ]
        if stage_doc_types:
            unreviewed = (
                db.table("documents")
                .select("id", count="exact")
                .eq("case_id", case_id)
                .eq("status", "pending")
                .in_("doc_type_code", stage_doc_types)
                .execute()
            )
            if unreviewed.count:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"{unreviewed.count} document(s) in this stage are still waiting for review.",
                )

    # RLS decides whether this person may sign off — `approvals_insert` requires
    # app.can_act_on_case, which excludes the exiting employee.
    inserted = (
        db.table("approvals")
        .insert(
            {
                "case_id": case_id,
                "stage_code": stage_code,
                "approver_id": actor.employee_id,
                "decision": body.decision,
                "comment": body.comment,
            }
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You cannot sign off this case."
        )

    if body.decision == "approved":
        stages = db.table("exit_stages").select("code, sort_order").order("sort_order").execute()
        order = [s["code"] for s in stages.data]
        index = order.index(stage_code)

        if index + 1 < len(order):
            changes: dict[str, object] = {"current_stage": order[index + 1]}
        else:
            changes = {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

        db.table("exit_cases").update(changes).eq("id", case_id).execute()

        write_audit(
            action="exit_cases.stage_advanced",
            entity_table="exit_cases",
            entity_id=case_id,
            actor=actor,
            case_id=case_id,
            before={"current_stage": stage_code},
            after=changes,
        )
    else:
        write_audit(
            action="exit_cases.stage_sent_back",
            entity_table="exit_cases",
            entity_id=case_id,
            actor=actor,
            case_id=case_id,
            after={"stage_code": stage_code, "comment": body.comment},
        )


@router.post(
    "/cases/{case_id}/override-stage", status_code=status.HTTP_204_NO_CONTENT
)
async def override_stage(case_id: str, body: StageOverride, actor: Actor) -> None:
    """Move a case to any stage, skipping the normal gates. HR only.

    The escape hatch for a genuinely stuck case — a leaver who has already gone,
    a clearance owner who left themselves, a task nobody can now complete. It
    bypasses the "everything in this stage is cleared" rule that `decide_stage`
    enforces, which is exactly why it demands a written reason and is recorded
    under its own audit action rather than looking like a normal advance.
    """
    if not actor.is_hr:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only HR can override a case's stage."
        )

    valid = actor.db.table("exit_stages").select("code").eq("code", body.stage_code).execute()
    if not valid.data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No such stage.")

    found = actor.db.table("exit_cases").select("current_stage").eq("id", case_id).execute()
    if not found.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")

    previous = found.data[0]["current_stage"]
    if previous == body.stage_code:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The case is already at that stage."
        )

    actor.db.table("exit_cases").update({"current_stage": body.stage_code}).eq(
        "id", case_id
    ).execute()

    write_audit(
        action="exit_cases.stage_overridden",
        entity_table="exit_cases",
        entity_id=case_id,
        actor=actor,
        case_id=case_id,
        before={"current_stage": previous},
        after={"current_stage": body.stage_code, "reason": body.reason},
    )


# ---------------------------------------------------------------------------
# Knowledge transfer
# ---------------------------------------------------------------------------


@router.patch("/cases/{case_id}/kt", status_code=status.HTTP_204_NO_CONTENT)
async def patch_kt_record(case_id: str, body: KtRecordPatch, actor: Actor) -> None:
    """Nominate a successor, or record the overall verdict on the handover.

    Both are the reviewer's call, not the leaver's — you do not choose who
    inherits your work, and you do not sign off your own handover.
    """
    changes = body.model_dump(exclude_none=True)
    if not changes:
        return

    case = actor.db.table("exit_cases").select("employee_id").eq("id", case_id).execute()
    if not case.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")

    if case.data[0]["employee_id"] == actor.employee_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Your manager nominates your successor and signs off the handover.",
        )

    if body.successor_id:
        if body.successor_id == case.data[0]["employee_id"]:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Someone cannot be their own successor.",
            )
        exists = (
            actor.db.table("employees")
            .select("id")
            .eq("id", body.successor_id)
            .eq("is_active", True)
            .execute()
        )
        if not exists.data:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "No such active employee."
            )

    if body.overall_status in ("verified", "gap"):
        changes["reviewed_by"] = actor.employee_id
        changes["reviewed_at"] = datetime.now(timezone.utc).isoformat()

    result = actor.db.table("kt_records").update(changes).eq("case_id", case_id).execute()
    if not result.data:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Knowledge transfer is not open for this case."
        )

    write_audit(
        action="kt_records.updated",
        entity_table="kt_records",
        entity_id=result.data[0]["id"],
        actor=actor,
        case_id=case_id,
        after=changes,
    )


# Audit actions that represent the caller deciding something, as opposed to
# merely touching a row. A document review and a KT verification are approvals
# in every sense a user means it, but neither writes to the `approvals` table —
# that one holds stage sign-offs only, which is why verifying a KT topic used
# to vanish from "already approved by you".
_DECISION_LABELS: dict[str, str] = {
    "documents.approved": "Approved document",
    "documents.rejected": "Sent document back",
    "kt_items.updated": "Reviewed KT topic",
    "kt_records.updated": "Signed off knowledge transfer",
}


@router.get("/approvals/recent")
async def recent_approvals(actor: Actor, limit: int = 20) -> list[dict[str, object]]:
    """Everything this person has decided lately, newest first.

    Deliberately drawn from two places. Stage sign-offs live in `approvals`
    with an `approver_id`; document reviews and KT verifications do not write
    there at all, and `kt_items` has no column recording who verified a topic —
    the audit log is the only record. Reading only `approvals` meant a manager
    who had just approved a KT saw an empty panel and reasonably concluded the
    feature was broken.
    """
    if actor.role == "employee":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Managers and HR only.")

    capped = min(limit, 50)

    stage_rows = (
        actor.db.table("approvals")
        .select("id, case_id, stage_code, decision, comment, decided_at")
        .eq("approver_id", actor.employee_id)
        .order("decided_at", desc=True)
        .limit(capped)
        .execute()
    ).data

    audit_rows = (
        actor.db.table("audit_log")
        .select("id, action, case_id, after, at")
        .eq("actor_id", actor.employee_id)
        .in_("action", list(_DECISION_LABELS))
        .order("at", desc=True)
        .limit(capped)
        .execute()
    ).data

    items: list[dict[str, object]] = [
        {
            "id": str(row["id"]),
            "case_id": row["case_id"],
            "kind": "stage",
            "decision": row["decision"],
            "label": row["stage_code"],
            "comment": row["comment"],
            "decided_at": row["decided_at"],
        }
        for row in stage_rows
    ]

    for row in audit_rows:
        after = row.get("after") or {}
        detail = after.get("coverage_status") or after.get("overall_status")
        items.append(
            {
                "id": f"audit-{row['id']}",
                "case_id": row["case_id"],
                "kind": "document" if row["action"].startswith("documents.") else "kt",
                # A KT topic marked `gap` was reviewed and found wanting, which
                # is a decision, not an approval — don't colour it as one.
                "decision": "rejected"
                if row["action"] == "documents.rejected" or detail == "gap"
                else "approved",
                "label": _DECISION_LABELS[row["action"]],
                "comment": str(detail) if detail else None,
                "decided_at": row["at"],
            }
        )

    # Drop decisions whose case has since been deleted. `audit_log.case_id` is
    # ON DELETE SET NULL, so removing a case leaves its history behind with no
    # way to say who it was about — and "Approved document — Unknown" is worse
    # than not listing it. Real cases are never deleted (no table has a DELETE
    # policy); these come from seed and test churn.
    items = [i for i in items if i["case_id"]]

    items.sort(key=lambda i: str(i["decided_at"]), reverse=True)
    items = items[:capped]
    if not items:
        return []

    stage_names = {
        s["code"]: s["name"]
        for s in actor.db.table("exit_stages").select("code, name").execute().data
    }
    cases = (
        actor.db.table("exit_cases")
        .select("id, employee:employees!exit_cases_employee_id_fkey(id, full_name)")
        .in_("id", [i["case_id"] for i in items if i["case_id"]])
        .execute()
    ).data
    employee_for = {c["id"]: c["employee"] for c in cases}

    return [
        {
            **item,
            "stage_code": item["label"] if item["kind"] == "stage" else None,
            "stage_name": stage_names.get(str(item["label"]), str(item["label"])),
            "employee": employee_for.get(str(item["case_id"])),
        }
        for item in items
    ]


@router.get("/cases/{case_id}/kt")
async def get_kt(case_id: str, actor: Actor) -> dict[str, object] | None:
    records = actor.db.table("kt_records").select("*").eq("case_id", case_id).execute()
    if not records.data:
        return None

    record = records.data[0]
    items = (
        actor.db.table("kt_items")
        .select("*")
        .eq("kt_record_id", record["id"])
        .order("sort_order")
        .execute()
    )
    return {**record, "items": items.data}


@router.post("/cases/{case_id}/kt/items", status_code=status.HTTP_201_CREATED)
async def add_kt_item(case_id: str, body: KtItemCreate, actor: Actor) -> dict[str, object]:
    records = actor.db.table("kt_records").select("id").eq("case_id", case_id).execute()
    if not records.data:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Knowledge transfer has not been opened for this case yet.",
        )
    record_id = records.data[0]["id"]

    existing = (
        actor.db.table("kt_items")
        .select("id", count="exact")
        .eq("kt_record_id", record_id)
        .execute()
    )

    inserted = (
        actor.db.table("kt_items")
        .insert(
            {
                "kt_record_id": record_id,
                "topic": body.topic,
                "detail": body.detail or None,
                "sort_order": (existing.count or 0) + 1,
            }
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot edit this record.")
    return inserted.data[0]


@router.patch("/cases/{case_id}/kt/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def patch_kt_item(
    case_id: str, item_id: str, body: KtItemPatch, actor: Actor
) -> None:
    changes = body.model_dump(exclude_none=True)
    if not changes:
        return

    # Only a reviewer may mark a topic verified or flag it as a gap. The exiting
    # employee must not be able to sign off their own handover.
    if changes.get("coverage_status") in ("verified", "gap"):
        case = actor.db.table("exit_cases").select("employee_id").eq("id", case_id).execute()
        if case.data and case.data[0]["employee_id"] == actor.employee_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Your manager decides whether a topic is verified.",
            )

    result = actor.db.table("kt_items").update(changes).eq("id", item_id).execute()
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found.")

    write_audit(
        action="kt_items.updated",
        entity_table="kt_items",
        entity_id=item_id,
        actor=actor,
        case_id=case_id,
        after=changes,
    )


# ---------------------------------------------------------------------------
# Exit interview
#
# RLS on `exit_interviews` excludes managers entirely — raw responses are often
# about them. They see only the derived summary, released by HR.
# ---------------------------------------------------------------------------


@router.get("/cases/{case_id}/interview")
async def get_interview(case_id: str, actor: Actor) -> dict[str, object] | None:
    found = actor.db.table("exit_interviews").select("*").eq("case_id", case_id).execute()
    return found.data[0] if found.data else None


@router.put("/cases/{case_id}/interview", status_code=status.HTTP_204_NO_CONTENT)
async def save_interview(case_id: str, body: InterviewBody, actor: Actor) -> None:
    existing = (
        actor.db.table("exit_interviews").select("*").eq("case_id", case_id).execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No exit interview is open.")

    if existing.data[0]["submitted_at"]:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This interview has already been submitted."
        )

    changes: dict[str, object] = {"responses": body.responses}
    if body.submit:
        changes["submitted_at"] = datetime.now(timezone.utc).isoformat()

    result = (
        actor.db.table("exit_interviews").update(changes).eq("case_id", case_id).execute()
    )
    if not result.data:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the exiting employee can fill this in."
        )

    if body.submit:
        # Response content is never audited — only the fact of submission.
        write_audit(
            action="exit_interviews.submitted",
            entity_table="exit_interviews",
            entity_id=existing.data[0]["id"],
            actor=actor,
            case_id=case_id,
        )
