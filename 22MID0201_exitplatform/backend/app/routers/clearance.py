"""The IT and Finance work queues.

One endpoint serves both. IT and Finance do the same shape of job — a list of
people leaving, the tasks this function owns on each, and a sign-off once they
are done — so the difference between the two dashboards is which `owner_role`
the rows carry, and that comes from who is signed in.

Scope is RLS's job, not this file's. Migration 0011 gives these roles read
access to cases where their role owns a task, and write access to those tasks
and their own stage only. Everything here queries through the caller's own
client, so IT asking for the queue gets IT's cases because the database says
so, not because of a filter written here.

Sorted by last working day. For a clearance function the only useful ordering
is "who leaves soonest", and anyone already past their last day with access
still live is the thing you want at the top of the screen.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.deps import Actor, CLEARANCE_ROLES
from app.services.audit import write_audit

router = APIRouter(tags=["clearance"])

OPEN_STATES = ("pending", "in_progress", "blocked")


@router.get("/clearance/queue")
async def clearance_queue(actor: Actor) -> dict[str, Any]:
    """Everything an IT or Finance dashboard renders, in one request."""
    if actor.role not in CLEARANCE_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This queue is for IT and Finance."
        )

    db = actor.db
    today = date.today()

    cases = (
        db.table("exit_cases")
        .select(
            "id, current_stage, last_working_day, status,"
            " employee:employees!exit_cases_employee_id_fkey"
            "(id, full_name, emp_code, department, designation)"
        )
        .in_("status", ["draft", "active", "on_hold", "completed"])
        .order("last_working_day")
        .execute()
    ).data
    if not cases:
        return {"role": actor.role, "stage_code": None, "people": [], "flagged": 0}

    case_ids = [c["id"] for c in cases]

    # Only this role's tasks. The policies would let them read the whole
    # checklist, but a queue is about what *you* have to do.
    mine = (
        db.table("case_tasks")
        .select("id, case_id, title, description, status, due_date, sla_breached, stage_code")
        .in_("case_id", case_ids)
        .eq("owner_role", actor.role)
        .order("sort_order")
        .execute()
    ).data

    stage_code = mine[0]["stage_code"] if mine else None

    signed_off = {
        a["case_id"]
        for a in (
            db.table("approvals")
            .select("case_id, stage_code, decision")
            .in_("case_id", case_ids)
            .eq("decision", "approved")
            .execute()
        ).data
        if a["stage_code"] == stage_code
    }

    by_case: dict[str, list[dict[str, Any]]] = {}
    for task in mine:
        by_case.setdefault(task["case_id"], []).append(task)

    # A stage cannot be signed off while *anyone's* task in it is open — not
    # just this role's. IT_CLEARANCE holds "Return laptop", which belongs to the
    # employee. Without this the button would look ready and the sign-off would
    # come back 409, so the queue names who is actually holding the stage up.
    others_open: dict[str, list[dict[str, str]]] = {}
    if stage_code:
        for row in (
            db.table("case_tasks")
            .select("case_id, title, owner_role, status")
            .in_("case_id", case_ids)
            .eq("stage_code", stage_code)
            .neq("owner_role", actor.role)
            .in_("status", list(OPEN_STATES))
            .execute()
        ).data:
            others_open.setdefault(row["case_id"], []).append(
                {"title": row["title"], "owner_role": row["owner_role"]}
            )

    # Only the itemisation this role works with. IT has no use for a settlement
    # breakdown, and sending it would put salary lines in front of them for no
    # reason. RLS would allow it; that is not a reason to.
    assets_by_case: dict[str, list[dict[str, Any]]] = {}
    access_by_case: dict[str, list[dict[str, Any]]] = {}
    settlement_by_case: dict[str, list[dict[str, Any]]] = {}

    if actor.role == "it":
        for row in (
            db.table("case_assets").select("*").in_("case_id", case_ids)
            .order("sort_order").execute()
        ).data:
            assets_by_case.setdefault(row["case_id"], []).append(row)
        for row in (
            db.table("case_access").select("*").in_("case_id", case_ids)
            .order("sort_order").execute()
        ).data:
            access_by_case.setdefault(row["case_id"], []).append(row)
    else:
        for row in (
            db.table("case_settlement").select("*").in_("case_id", case_ids)
            .order("sort_order").execute()
        ).data:
            settlement_by_case.setdefault(row["case_id"], []).append(row)

    people = []
    flagged = 0
    for case in cases:
        tasks = by_case.get(case["id"], [])
        if not tasks:
            continue

        open_tasks = [t for t in tasks if t["status"] in OPEN_STATES]
        last_day = date.fromisoformat(case["last_working_day"])

        access = access_by_case.get(case["id"], [])
        live_access = [a for a in access if a["status"] == "active"]

        # For IT the sharpest signal is not an open task but a live account
        # belonging to someone who has already left. Count that, not the task.
        gone = last_day < today
        at_risk = gone and (bool(live_access) if actor.role == "it" else bool(open_tasks))
        if at_risk:
            flagged += 1

        people.append(
            {
                "case_id": case["id"],
                "employee": case["employee"],
                "current_stage": case["current_stage"],
                "last_working_day": case["last_working_day"],
                "days_remaining": (last_day - today).days,
                "tasks": tasks,
                "open_count": len(open_tasks),
                "done_count": len(tasks) - len(open_tasks),
                "at_risk": at_risk,
                "signed_off": case["id"] in signed_off,
                "blocked_by": others_open.get(case["id"], []),
                "assets": assets_by_case.get(case["id"], []),
                "access": access,
                "settlement": settlement_by_case.get(case["id"], []),
                "live_access": len(live_access),
                "elevated_live": sum(1 for a in live_access if a["is_elevated"]),
            }
        )

    # Overdue first, then soonest to leave.
    people.sort(key=lambda p: (not p["at_risk"], p["days_remaining"]))

    return {
        "role": actor.role,
        "stage_code": stage_code,
        "people": people,
        "flagged": flagged,
    }


class AssetPatch(BaseModel):
    status: Literal["pending", "returned", "lost", "not_issued"]
    identifier: str | None = None
    condition: str | None = None
    note: str | None = None


class AccessPatch(BaseModel):
    status: Literal["active", "revoked", "not_applicable"]
    note: str | None = None


class SettlementPatch(BaseModel):
    status: Literal["pending", "confirmed", "not_applicable"]
    amount: float | None = None
    note: str | None = None


def _updated_row(table: str, row_id: str, changes: dict[str, Any], actor: Actor) -> dict[str, Any]:
    """Apply a change through the caller's own client and audit it.

    RLS decides whether it lands — IT may write assets and access, Finance
    settlement lines, HR any of them. An empty result means the policy refused,
    which is a 403 rather than a silent no-op.
    """
    result = actor.db.table(table).update(changes).eq("id", row_id).execute()
    if not result.data:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You cannot change this item, or it does not exist.",
        )

    row = result.data[0]
    write_audit(
        action=f"{table}.updated",
        entity_table=table,
        entity_id=row_id,
        actor=actor,
        case_id=row["case_id"],
        after=changes,
    )
    return row


@router.patch("/clearance/assets/{asset_id}")
async def update_asset(asset_id: str, body: AssetPatch, actor: Actor) -> dict[str, Any]:
    """Record an item as returned, lost, or never issued."""
    changes: dict[str, Any] = {"status": body.status}
    for field in ("identifier", "condition", "note"):
        value = getattr(body, field)
        if value is not None:
            changes[field] = value

    if body.status == "returned":
        changes["returned_at"] = datetime.now(timezone.utc).isoformat()
        changes["returned_to"] = actor.employee_id
    else:
        changes["returned_at"] = None
        changes["returned_to"] = None

    return _updated_row("case_assets", asset_id, changes, actor)


@router.patch("/clearance/access/{access_id}")
async def update_access(access_id: str, body: AccessPatch, actor: Actor) -> dict[str, Any]:
    """Record a system as revoked, still live, or not applicable."""
    changes: dict[str, Any] = {"status": body.status}
    if body.note is not None:
        changes["note"] = body.note

    if body.status == "revoked":
        changes["revoked_at"] = datetime.now(timezone.utc).isoformat()
        changes["revoked_by"] = actor.employee_id
    else:
        # Reopening clears the record of who revoked it — keeping a stale
        # revoker on a live account would misread as "someone handled this".
        changes["revoked_at"] = None
        changes["revoked_by"] = None

    return _updated_row("case_access", access_id, changes, actor)


@router.patch("/clearance/settlement/{item_id}")
async def update_settlement(
    item_id: str, body: SettlementPatch, actor: Actor
) -> dict[str, Any]:
    """Fill in or confirm one line of the full-and-final settlement."""
    changes: dict[str, Any] = {"status": body.status}
    if body.amount is not None:
        changes["amount"] = body.amount
    if body.note is not None:
        changes["note"] = body.note
    return _updated_row("case_settlement", item_id, changes, actor)
