"""Keep a task in step with the document that satisfies it.

The problem this solves
-----------------------
`case_tasks` and `documents` both carry a `doc_type_code`, but nothing joined
them. A task like "Upload knowledge transfer document" and the KT document the
employee actually uploaded were two unrelated rows. So the employee submitted,
the manager approved, and the task still read `pending` — forever. The
completion percentage never moved, and the employee had no way to see that
their manager had approved anything.

The rule
--------
A document-backed task is a mirror of its document:

    uploaded / submitted  ->  in_progress   (with you, waiting on review)
    approved              ->  completed
    rejected              ->  pending       (back with the employee)

`in_progress` deliberately carries "submitted, awaiting approval" rather than
`task_status` gaining a `submitted` value. The document's own status already
records submitted/approved/rejected; putting it in the task enum too would mean
two places to keep in agreement, and the frontend can derive the fuller wording
from the pair (see `taskDisplayStatus` in frontend/src/lib/format.ts).

Writes go through `service_db()` on purpose. This is a system consequence of a
change the caller was already authorised to make — the same category as task
template expansion in `services/cases.py` — not a second action taken on the
user's behalf. In particular a manager approving a document must be able to
complete a task assigned to the employee, which `case_tasks`'s own policy
correctly forbids them from doing directly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from app.deps import ActorContext, service_db
from app.services.audit import write_audit

DocumentState = Literal["submitted", "approved", "rejected"]


def is_outbound(doc_type_code: str) -> str | None:
    """The role that issues this document, or None if the employee submits it.

    Documents travel in two directions and the difference decides whether there
    is a review step at all.

    *Inbound* — a resignation letter, a KT document, a signed NDA — is the
    employee proving something to the company. Somebody else checks it, so it
    goes pending -> approved or rejected.

    *Outbound* — a relieving letter, an experience letter, a no-dues
    certificate, a settlement statement — is the company issuing something to
    the employee. There is nobody to check it: HR is the authority on what HR's
    own letter says, and `review_document` correctly refuses to let anyone
    approve their own upload. Treating these as inbound left them stuck at
    "waiting for review" with no one able to clear them, which is why HR had no
    way to actually send a relieving letter.

    `document_types.owner_role` already records this. Anything not owned by the
    employee is issued rather than submitted.
    """
    found = (
        service_db()
        .table("document_types")
        .select("owner_role")
        .eq("code", doc_type_code)
        .limit(1)
        .execute()
    )
    if not found.data:
        return None
    owner = found.data[0]["owner_role"]
    return None if owner == "employee" else owner

_TASK_STATUS_FOR: dict[str, str] = {
    "submitted": "in_progress",
    "approved": "completed",
    "rejected": "pending",
}


def sync_task_for_document(
    actor: ActorContext,
    *,
    case_id: str,
    doc_type_code: str | None,
    document_state: DocumentState,
) -> dict[str, Any] | None:
    """Move the task that this document satisfies, and audit the move.

    Returns the updated task row, or None when there is nothing to do — no
    `doc_type_code`, no task expecting that document, or the task is already in
    the right state. A missing task is normal and not an error: a document type
    need not have a task, and HR can upload something ad hoc.
    """
    if not doc_type_code:
        return None

    new_status = _TASK_STATUS_FOR[document_state]
    db = service_db()

    found = (
        db.table("case_tasks")
        .select("id, status, title, assignee_id")
        .eq("case_id", case_id)
        .eq("doc_type_code", doc_type_code)
        .limit(1)
        .execute()
    )
    if not found.data:
        return None

    task = found.data[0]
    if task["status"] == new_status:
        return None

    # A waived task stays waived: HR has already decided the obligation does not
    # apply, and a late upload should not silently reinstate it.
    if task["status"] == "waived":
        return None

    changes: dict[str, Any] = {"status": new_status}
    if new_status == "completed":
        changes["completed_at"] = datetime.now(timezone.utc).isoformat()
        changes["completed_by"] = actor.employee_id
        # Approving late still clears the breach; the delay lives in audit_log.
        changes["sla_breached"] = False
    else:
        changes["completed_at"] = None
        changes["completed_by"] = None

    updated = db.table("case_tasks").update(changes).eq("id", task["id"]).execute()
    if not updated.data:
        return None

    write_audit(
        action="case_tasks.status_changed",
        entity_table="case_tasks",
        entity_id=task["id"],
        actor=actor,
        case_id=case_id,
        before={"status": task["status"]},
        after={"status": new_status, "because": f"document {document_state}"},
    )
    return updated.data[0]
