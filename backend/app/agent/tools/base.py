"""Shared plumbing every tool module (`reads.py`, `drafts.py`, `writes.py`)
imports — kept out of `__init__.py` so those modules can import it without a
circular import back through the package that assembles them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from app.deps import ActorContext, service_db
from app.services.audit import write_audit


@dataclass(frozen=True)
class ToolContext:
    """What a tool call actually needs — bundled so `tool_node` threads one
    object instead of three separate args through every call.
    """

    actor: ActorContext
    run_id: str | None
    case_id: str | None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[..., str]

    def as_tool_def(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


def wrap_untrusted(text: str) -> str:
    """Rule 3: document/interview text is data the exiting employee wrote,
    not instructions — wrapping it makes that boundary visible in the
    transcript the model actually sees, not just asserted in its system
    prompt."""
    return f"<untrusted_content>\n{text}\n</untrusted_content>"


def dump(obj: Any) -> str:
    return json.dumps(obj, default=str)


def resolve_case_id(ctx: ToolContext, case_id: str | None) -> str | None:
    return case_id or ctx.case_id


def is_self_targeting(ctx: ToolContext, case_id: str) -> bool:
    """Rule 3 defence: an action that targets the requesting employee's own
    clearance gets flagged so a human reviewer can't skip it via whichever
    approval path would normally apply to someone else's case."""
    row = ctx.actor.db.table("exit_cases").select("employee_id").eq("id", case_id).limit(1).execute()
    if not row.data:
        return False
    return row.data[0]["employee_id"] == ctx.actor.employee_id


def draft_action(
    ctx: ToolContext,
    *,
    kind: str,
    summary: str,
    payload: dict[str, Any],
    case_id: str | None = None,
    self_targeting: bool = False,
) -> str:
    """Every sensitive tool's terminal step (rule 2): write a pending_approval
    row, audit it, and return a plain-text confirmation the model can relay.
    Uses `service_db()` deliberately — this is a system-authored record of
    what the agent proposed, the same category of write `services/audit.py`
    already makes for `audit_log`, not a rule-1 "read on the actor's behalf".
    """
    cid = case_id if case_id is not None else ctx.case_id
    row = (
        service_db()
        .table("agent_actions")
        .insert(
            {
                "run_id": ctx.run_id,
                "case_id": cid,
                "kind": kind,
                "summary": summary,
                "payload": payload,
                "self_targeting": self_targeting,
            }
        )
        .execute()
    )
    action_id = row.data[0]["id"]
    write_audit(
        action=f"agent_actions.drafted.{kind}",
        entity_table="agent_actions",
        entity_id=action_id,
        actor_type="agent",
        case_id=cid,
        run_id=ctx.run_id,
        after={"kind": kind, "summary": summary},
    )
    return f"Drafted (id={action_id}, status=pending_approval): {summary}"
