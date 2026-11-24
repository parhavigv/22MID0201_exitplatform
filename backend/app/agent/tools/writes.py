"""CLAUDE.md's one unguarded write: `update_task_status`. Real, immediate,
allow-listed transitions only. RLS plus this allow-list is what makes it safe
for the model to call directly instead of drafting.

The allow-list below is deliberately *stricter* than `routers/tasks.py`, which
has no transition table at all — it accepts any status and gates only "waived"
to HR. That is correct for a person: an employee ticking off a task goes
straight from `pending` to `completed`, which this table forbids. A model
should have to move a task through `in_progress` first, so a mistaken jump to
`completed` is not one tool call away.

(An earlier version of this docstring claimed the two mirrored each other
exactly. They never have.)
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.agent.tools.base import ToolContext, ToolSpec
from app.services.audit import write_audit

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"in_progress", "blocked"},
    "in_progress": {"completed", "blocked"},
    "blocked": {"in_progress"},
    "completed": set(),
    "waived": set(),
}

# Same restriction routers/tasks.py applies: waiving clears an obligation
# rather than fulfilling it, so only HR may do it.
RESTRICTED = {"waived"}


def update_task_status(ctx: ToolContext, task_id: str, status: str) -> str:
    existing = ctx.actor.db.table("case_tasks").select("*").eq("id", task_id).limit(1).execute()
    if not existing.data:
        return f"No task visible for id={task_id} — it may not exist, or your access doesn't include it."
    before = existing.data[0]

    if status not in ALLOWED_TRANSITIONS.get(before["status"], set()):
        return (
            f"Refused: {before['status']!r} -> {status!r} is not an allow-listed transition. "
            f"Allowed from {before['status']!r}: {sorted(ALLOWED_TRANSITIONS.get(before['status'], set())) or 'none'}."
        )
    if status in RESTRICTED and not ctx.actor.is_hr:
        return f"Refused: only HR can set a task to {status!r}."

    now = datetime.now(timezone.utc).isoformat()
    changes: dict[str, object] = {"status": status}
    if status == "completed":
        changes["completed_at"] = now
        changes["completed_by"] = ctx.actor.employee_id
        changes["sla_breached"] = False
    else:
        changes["completed_at"] = None
        changes["completed_by"] = None

    result = ctx.actor.db.table("case_tasks").update(changes).eq("id", task_id).execute()
    if not result.data:
        return "Refused: RLS did not allow this change (not your task to change)."

    write_audit(
        action="case_tasks.status_changed",
        entity_table="case_tasks",
        entity_id=task_id,
        actor=ctx.actor,
        actor_type="agent",
        case_id=before["case_id"],
        run_id=ctx.run_id,
        before={"status": before["status"]},
        after={"status": status},
    )
    return f"Task {task_id!r} moved {before['status']!r} -> {status!r}."


TOOLS = [
    ToolSpec(
        name="update_task_status",
        description=(
            "Move a task to a new status along an allow-listed transition "
            "(pending->in_progress/blocked, in_progress->completed/blocked, "
            "blocked->in_progress). Setting 'waived' requires HR. This is a "
            "real write, not a draft."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "in_progress", "blocked", "completed", "waived"]},
            },
            "required": ["task_id", "status"],
        },
        fn=update_task_status,
    ),
]
