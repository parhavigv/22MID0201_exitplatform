"""Phase 4 — executor.py

The only place where an approved agent action becomes a real effect.

Rule 2 says draft tools never act — they write agent_actions with
status='pending_approval'. This module is called once a human approves via
POST /agent/actions/{id}/decide. The effect happens here, the action row moves
to 'executed', and an audit row is written for the execution.

If anything raises, the row moves to 'failed' with a failure_reason, and the
error is logged but not re-raised — the HTTP response already went back with
204 at the point of approval; executor runs async after the response is sent.

All DB writes go through service_db() because these are system-generated
effects (same reasoning as case creation — see services/cases.py).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.deps import service_db
from app.services.audit import write_audit
from app.services.email import Message, get_sender

log = logging.getLogger("app.services.executor")


def execute(action: dict[str, Any], approver_id: str) -> None:
    """Perform the real effect for an approved agent_action row.

    Called synchronously in a background thread after the HTTP 204 is sent.
    Never raises — failures are recorded in the action row itself.
    """
    action_id = action["id"]
    kind = action["kind"]
    # If the human edited the payload in the UI, that's stored in approved_payload
    payload: dict[str, Any] = action.get("approved_payload") or action.get("payload") or {}

    db = service_db()
    now = datetime.now(timezone.utc).isoformat()

    try:
        _dispatch(kind, payload, action, approver_id)

        db.table("agent_actions").update({
            "status": "executed",
            "executed_at": now,
        }).eq("id", action_id).execute()

        write_audit(
            action=f"agent_actions.executed.{kind}",
            entity_table="agent_actions",
            entity_id=action_id,
            actor_id=approver_id,
            actor_type="human",
            case_id=action.get("case_id"),
            before={"status": "approved"},
            after={"status": "executed"},
        )
        log.info("executor: executed %s id=%s", kind, action_id)

    except Exception as exc:  # noqa: BLE001
        log.exception("executor: failed %s id=%s: %s", kind, action_id, exc)
        db.table("agent_actions").update({
            "status": "failed",
            "failure_reason": str(exc)[:500],
        }).eq("id", action_id).execute()
        write_audit(
            action=f"agent_actions.failed.{kind}",
            entity_table="agent_actions",
            entity_id=action_id,
            actor_id=approver_id,
            actor_type="human",
            case_id=action.get("case_id"),
            after={"status": "failed", "reason": str(exc)[:200]},
        )


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

def _dispatch(kind: str, payload: dict, action: dict, approver_id: str) -> None:
    match kind:
        case "generate_exit_checklist":
            _generate_checklist(payload)
        case "draft_notification":
            _send_notification(payload, action["id"])
        case "draft_escalation":
            _send_escalation(payload, action["id"])
        case "review_kt_document":
            _apply_kt_review(payload)
        case "assess_exit_risk":
            _apply_risk_score(payload)
        case "verify_compliance":
            _record_compliance(payload, action["id"])
        case "summarize_exit_interview":
            _apply_interview_summary(payload)
        case "request_document":
            _notify_document_request(payload, action["id"])
        case "flag_policy_breach":
            _notify_policy_breach(payload, action["id"])
        case _:
            log.warning("executor: unknown action kind %r — nothing done", kind)


# ---------------------------------------------------------------------------
# Effect implementations
# ---------------------------------------------------------------------------

def _generate_checklist(payload: dict) -> None:
    """Insert agent-generated tasks into case_tasks."""
    db = service_db()
    case_id = payload["case_id"]
    additions = payload.get("additions") or []
    if not additions:
        return

    rows = []
    for i, task in enumerate(additions):
        rows.append({
            "id": str(uuid.uuid4()),
            "case_id": case_id,
            "stage_code": task["stage_code"],
            "title": task["title"],
            "description": task.get("description"),
            "owner_role": task["owner_role"],
            "generated_by": "agent",
            "sort_order": 9000 + i,  # after template tasks
        })

    db.table("case_tasks").insert(rows).execute()
    log.info("executor: added %d checklist tasks to case %s", len(rows), case_id[:8])


def _send_notification(payload: dict, source_action_id: str) -> None:
    """Insert a notification row and optionally send an email."""
    db = service_db()
    db.table("notifications").insert({
        "id": str(uuid.uuid4()),
        "recipient_id": payload["recipient_id"],
        "title": payload["title"],
        "body": payload["body"],
        "source_action_id": source_action_id,
    }).execute()

    try:
        sender = get_sender()
        sender.send(Message(
            to=payload.get("recipient_email", ""),
            subject=payload["title"],
            body=payload["body"],
        ))
    except Exception as exc:
        log.warning("executor: email send failed (notification still created): %s", exc)


def _send_escalation(payload: dict, source_action_id: str) -> None:
    """Insert an escalation notification for the HR Business Partner."""
    db = service_db()

    if payload.get("recipient_id"):
        hr_rows_data = (
            db.table("employees")
            .select("id, work_email")
            .eq("id", payload["recipient_id"])
            .execute()
        ).data
    else:
        hr_rows_data = (
            db.table("employees")
            .select("id, work_email")
            .eq("app_role", "hr")
            .eq("is_active", True)
            .execute()
        ).data

    title = f"Escalation: {payload.get('current_stage', 'case')}"
    body = payload["reason"]

    for hr in hr_rows_data:
        db.table("notifications").insert({
            "id": str(uuid.uuid4()),
            "recipient_id": hr["id"],
            "title": title,
            "body": body,
            "source_action_id": source_action_id,
        }).execute()
        try:
            get_sender().send(Message(to=hr.get("work_email", ""), subject=title, body=body))
        except Exception as exc:
            log.warning("executor: escalation email failed: %s", exc)


def _apply_kt_review(payload: dict) -> None:
    """Update kt_items with the agent's coverage assessment."""
    db = service_db()
    update: dict[str, Any] = {
        "coverage_status": payload["coverage_status"],
    }
    if payload.get("gap_note"):
        update["gap_note"] = payload["gap_note"]

    db.table("kt_items").update(update).eq("id", payload["kt_item_id"]).execute()
    log.info(
        "executor: kt_item %s set to %s",
        payload["kt_item_id"][:8], payload["coverage_status"],
    )


def _apply_risk_score(payload: dict) -> None:
    """Write the assessed risk score back to exit_cases."""
    db = service_db()
    db.table("exit_cases").update({
        "risk_score": payload["risk_score"],
        "risk_assessed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", payload["case_id"]).execute()
    log.info(
        "executor: risk score %s for case %s",
        payload["risk_score"], payload["case_id"][:8],
    )


def _record_compliance(payload: dict, source_action_id: str) -> None:
    """Notify HR of compliance gaps. No separate table yet — lands in notifications."""
    if payload.get("compliant"):
        log.info("executor: compliance verified for case %s — all clear", payload["case_id"][:8])
        return

    db = service_db()
    gaps = payload.get("gaps") or []
    title = f"Compliance gaps — case {payload['case_id'][:8]}"
    body = "Compliance gaps found:\n" + "\n".join(f"• {g}" for g in gaps)

    hr_rows = (
        db.table("employees")
        .select("id, work_email")
        .eq("app_role", "hr")
        .eq("is_active", True)
        .execute()
    )
    for hr in hr_rows.data:
        db.table("notifications").insert({
            "id": str(uuid.uuid4()),
            "recipient_id": hr["id"],
            "title": title,
            "body": body,
            "source_action_id": source_action_id,
        }).execute()
        try:
            get_sender().send(Message(to=hr.get("work_email", ""), subject=title, body=body))
        except Exception as exc:
            log.warning("executor: compliance email failed: %s", exc)


def _apply_interview_summary(payload: dict) -> None:
    """Persist the AI-generated interview summary back to exit_interviews."""
    db = service_db()
    db.table("exit_interviews").update({
        "sentiment": payload.get("sentiment"),
        "themes": payload.get("themes"),
        "summary": payload.get("summary"),
        "analysed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", payload["interview_id"]).execute()
    log.info(
        "executor: interview summary written for interview %s",
        payload["interview_id"][:8],
    )


def _notify_document_request(payload: dict, source_action_id: str) -> None:
    """Notify the case's employee that a document is needed."""
    db = service_db()
    case_id = payload["case_id"]

    case_row = (
        db.table("exit_cases")
        .select("employee_id, employee:employees!exit_cases_employee_id_fkey(id, work_email)")
        .eq("id", case_id)
        .limit(1)
        .execute()
    )
    if not case_row.data:
        log.warning("executor: case %s not found for document request", case_id[:8])
        return

    emp = case_row.data[0].get("employee") or {}
    employee_id = case_row.data[0]["employee_id"]
    title = f"Document needed: {payload.get('doc_type_name', payload['doc_type_code'])}"
    body = payload.get("reason") or "Please upload this required document to continue your exit process."

    db.table("notifications").insert({
        "id": str(uuid.uuid4()),
        "recipient_id": employee_id,
        "title": title,
        "body": body,
        "source_action_id": source_action_id,
    }).execute()
    try:
        get_sender().send(Message(to=emp.get("work_email", ""), subject=title, body=body))
    except Exception as exc:
        log.warning("executor: document request email failed: %s", exc)


def _notify_policy_breach(payload: dict, source_action_id: str) -> None:
    """Notify HR of a flagged policy breach."""
    db = service_db()
    severity = payload.get("severity", "medium").upper()
    title = f"Policy breach flagged [{severity}] — case {payload['case_id'][:8]}"
    body = payload["description"]

    hr_rows = (
        db.table("employees")
        .select("id, work_email")
        .eq("app_role", "hr")
        .eq("is_active", True)
        .execute()
    )
    for hr in hr_rows.data:
        db.table("notifications").insert({
            "id": str(uuid.uuid4()),
            "recipient_id": hr["id"],
            "title": title,
            "body": body,
            "source_action_id": source_action_id,
        }).execute()
        try:
            get_sender().send(Message(to=hr.get("work_email", ""), subject=title, body=body))
        except Exception as exc:
            log.warning("executor: policy breach email failed: %s", exc)
