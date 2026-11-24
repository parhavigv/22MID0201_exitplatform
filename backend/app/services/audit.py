"""
Audit trail.

Every state change writes here (CLAUDE.md rule 4). Writes go through the
service-role client because `audit_log` is deliberately not writable by
`authenticated` — a user must not be able to forge or suppress their own trail.
"""

from __future__ import annotations

from typing import Any, Literal

from app.deps import ActorContext, service_db

ActorType = Literal["human", "agent", "system"]


def write_audit(
    *,
    action: str,
    entity_table: str,
    entity_id: str,
    actor: ActorContext | None = None,
    actor_id: str | None = None,   # alternative when no ActorContext is available
    actor_type: ActorType = "human",
    case_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> None:
    """Record one state change.

    `action` is a dotted verb naming what happened, e.g.
    "documents.approved", "case_tasks.status_changed", "exit_cases.stage_advanced".
    Keep the vocabulary stable — the HR activity view groups on it.

    Pass `actor` (an ActorContext) when one is available; pass `actor_id`
    (a plain employee UUID string) from background/service-role paths like
    executor.py where no request context exists.
    """
    resolved_actor_id = (actor.employee_id if actor else None) or actor_id
    service_db().table("audit_log").insert(
        {
            "actor_id": resolved_actor_id,
            "actor_type": actor_type,
            "run_id": run_id,
            "action": action,
            "entity_table": entity_table,
            "entity_id": entity_id,
            "case_id": case_id,
            "before": before,
            "after": after,
        }
    ).execute()
