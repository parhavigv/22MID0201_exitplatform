"""Phase 7 — sweep.py

Autonomous nightly sweep over all active exit cases.

The sweep invokes the same LangGraph graph that the /agent/chat endpoint uses,
but with:
- trigger="sweep" instead of "chat"
- A system-role ActorContext using service_db() — the sweep agent needs HR-level
  visibility to see every active case, but still obeys rule 2 (draft only, never
  execute) and rule 4 (audit row per action).
- A seed message naming the sweep-specific workers: sla_escalation and
  policy_compliance_auditor. The supervisor routes to them because the seed
  message asks for exactly that work.

Why service_db for the sweep actor?
- The sweep runs as a system job, not on behalf of a human session. There is no
  JWT. The service-role client is exactly what rule 1 says to use for "executor,
  sweep job, audit writes — code paths that act as the system, not on behalf of
  a user." (deps.py module docstring)
- The workers still go through draft tools only — service_db lets them *read*
  all cases, but every sensitive *write* is still a pending_approval row in
  agent_actions waiting for a human.

Per-run action cap: SWEEP_ACTION_CAP (default 20) prevents a runaway sweep from
flooding the approval queue. The supervisor's own MAX_ITERATIONS (8) also fires
before this in most cases — the cap is a second line of defence.

Called from:
- backend/app/main.py via APScheduler (Phase 7)
- backend/scripts/run_sweep.py for manual / CI testing
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from app.deps import ActorContext, service_db
from app.agent.state import AgentContext

log = logging.getLogger("app.jobs.sweep")

SWEEP_ACTION_CAP = 20

def _sweep_employee_id() -> str:
    """The HR employee the sweep runs as.

    This was a sentinel UUID on the reasoning that no real person owns a sweep
    run. But `agent_runs.actor_id` is a foreign key into `employees`, so every
    run insert failed the constraint and the whole sweep errored on every case
    — silently, nightly, since it was written. Nothing surfaced it because the
    job logs failures and moves on.

    An active HR employee is the honest actor anyway: the sweep acts with HR's
    authority, and `agent_runs.trigger = 'sweep'` already distinguishes it from
    a person chatting.
    """
    found = (
        service_db()
        .table("employees")
        .select("id")
        .eq("app_role", "hr")
        .eq("is_active", True)
        .order("emp_code")
        .limit(1)
        .execute()
    )
    if not found.data:
        raise RuntimeError(
            "No active HR employee to run the sweep as — run apply_migrations.py --seed."
        )
    return found.data[0]["id"]

SWEEP_SEED_MESSAGE = """
You are running as part of the nightly automated sweep for the Exit Process Platform.

Your job for this run:
1. Route to the sla_escalation worker — check whether any tasks in this case are
   overdue or approaching their SLA, and draft escalation notifications for HR or
   the responsible manager if so.
2. Then route to the policy_compliance_auditor worker — check that the case is
   following required compliance steps (documents, sign-offs, notice period) and
   flag any gaps.

Do not chat. Do not ask questions. Draft any actions you find, then finish.
Only draft if there is something genuinely worth escalating — do not generate
noise for healthy cases.
""".strip()


@dataclass(frozen=True)
class SweepResult:
    case_id: str
    status: str            # "ok", "error"
    actions_drafted: int
    error: str | None = None


def _make_sweep_actor() -> ActorContext:
    """Build a pseudo ActorContext for the sweep job.

    Uses service_db() as the `db` field so the agent tools can read all active
    cases without an RLS-bound JWT. This is the one blessed bypass (rule 1
    exemption, same reasoning as executor.py and audit.py).
    """
    employee_id = _sweep_employee_id()
    return ActorContext(
        employee_id=employee_id,
        auth_user_id=employee_id,
        role="hr",
        full_name="Exit Copilot Sweep",
        email="",
        db=service_db(),
    )


def _count_pending_actions_before(db, case_id: str) -> int:
    result = (
        db.table("agent_actions")
        .select("id", count="exact")
        .eq("case_id", case_id)
        .eq("status", "pending_approval")
        .execute()
    )
    return result.count or 0


def sweep_case(case_id: str) -> SweepResult:
    """Run the sweep graph for a single case.

    Returns a SweepResult describing what happened. Never raises — failures
    are logged and returned in the result so the caller can continue with
    other cases.
    """
    from app.agent.graph import build_graph  # lazy — graph init is heavy

    actor = _make_sweep_actor()
    db = service_db()

    before_count = _count_pending_actions_before(db, case_id)

    try:
        context = AgentContext(actor=actor, trigger="sweep", case_id=case_id)
        graph = build_graph()
        config = {"configurable": {"thread_id": f"sweep:{case_id}"}}

        state_in: dict[str, Any] = {
            "messages": [{"role": "user", "content": SWEEP_SEED_MESSAGE}],
            "run_id": None,
            "usage": None,
            "error": None,
            "pending_tool_calls": [],
            "active_worker": None,
            "worker_messages": [],
            "route_call_id": None,
            "worker_history": [],
            "tool_trace": [],
            "iterations": 0,
        }

        result = graph.invoke(state_in, config=config, context=context)

        if result.get("error"):
            log.warning("sweep: case %s graph error: %s", case_id[:8], result["error"])
            return SweepResult(case_id=case_id, status="error", actions_drafted=0, error=result["error"])

        after_count = _count_pending_actions_before(db, case_id)
        drafted = max(0, after_count - before_count)
        log.info("sweep: case %s — %d action(s) drafted", case_id[:8], drafted)
        return SweepResult(case_id=case_id, status="ok", actions_drafted=drafted)

    except Exception as exc:  # noqa: BLE001
        log.exception("sweep: case %s failed: %s", case_id[:8], exc)
        return SweepResult(case_id=case_id, status="error", actions_drafted=0, error=str(exc)[:300])


def sweep_all_active() -> list[SweepResult]:
    """Sweep every active exit case.

    Fetches the list via service_db, then calls sweep_case for each one.
    The per-case action cap is enforced by the graph's loop guard; this
    function adds a total-actions-per-sweep cap as a second line of defence.
    """
    db = service_db()
    cases_result = (
        db.table("exit_cases")
        .select("id, employee_id, current_stage")
        .eq("status", "active")
        .order("created_at")
        .execute()
    )

    cases = cases_result.data
    log.info("sweep: found %d active case(s)", len(cases))

    results: list[SweepResult] = []
    total_drafted = 0

    for case in cases:
        if total_drafted >= SWEEP_ACTION_CAP:
            log.warning(
                "sweep: reached action cap (%d) — skipping remaining %d case(s)",
                SWEEP_ACTION_CAP, len(cases) - len(results),
            )
            break

        result = sweep_case(case["id"])
        results.append(result)
        total_drafted += result.actions_drafted

    ok = sum(1 for r in results if r.status == "ok")
    err = sum(1 for r in results if r.status == "error")
    log.info("sweep: done — %d ok, %d error, %d action(s) total", ok, err, total_drafted)
    return results
