"""HR analytics — read-only aggregations over the live DB.

GET /analytics   — dashboard stats for the Analytics page

All queries run through service_db() (not the RLS-bound client) because we
need cross-employee aggregations that RLS would otherwise block.  The endpoint
itself is HR-gated, so the bypass is intentional and audited at the router
level, not inside the query.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict

from fastapi import APIRouter, HTTPException, status

from app.deps import Actor, service_db

log = logging.getLogger("app.routers.analytics")
router = APIRouter(tags=["analytics"])

# Human-readable stage names — mirrors the seeded exit_stages table.
_STAGE_NAMES: dict[str, str] = {
    "RESIGNATION_SUBMITTED": "Resignation submitted",
    "MANAGER_ACK": "Manager acknowledgement",
    "KT_PLANNING": "KT planning",
    "KT_EXECUTION": "KT execution",
    "IT_CLEARANCE": "IT clearance",
    "FINANCE_CLEARANCE": "Finance clearance",
    "ADMIN_ASSET_RETURN": "Admin / asset return",
    "EXIT_INTERVIEW": "Exit interview",
    "FINAL_SETTLEMENT": "Final settlement",
    "RELIEVING_LETTER": "Relieving letter",
}


@router.get("/analytics")
async def get_analytics(actor: Actor) -> dict:
    """Aggregate stats for the HR analytics dashboard.

    Returns case counts, average duration, bottleneck stage, department
    breakdown, and agent activity — all in one call so the page loads with
    a single request.
    """
    if actor.role != "hr":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "HR only.")

    db = service_db()

    # ── Case counts ──────────────────────────────────────────────────────────
    cases_raw = db.table("exit_cases").select(
        "id, status, resignation_date, last_working_day, employee_id, current_stage"
    ).execute()
    cases = cases_raw.data

    status_counts: Counter[str] = Counter(c["status"] for c in cases)

    # ── Average notice period duration (resignation → LWD) ───────────────────
    from datetime import date

    durations: list[int] = []
    for c in cases:
        try:
            r = date.fromisoformat(c["resignation_date"])
            l = date.fromisoformat(c["last_working_day"])
            durations.append((l - r).days)
        except Exception:
            pass
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0.0

    # ── Department breakdown ──────────────────────────────────────────────────
    emps_raw = db.table("employees").select("id, department").execute()
    dept_by_id: dict[str, str] = {e["id"]: e["department"] for e in emps_raw.data}

    dept_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"active": 0, "completed": 0, "on_hold": 0, "total": 0}
    )
    for c in cases:
        dept = dept_by_id.get(c["employee_id"], "Unknown")
        dept_stats[dept]["total"] += 1
        if c["status"] in ("active", "completed", "on_hold"):
            dept_stats[dept][c["status"]] += 1

    by_department = [
        {"department": k, **v}
        for k, v in sorted(dept_stats.items(), key=lambda x: -x[1]["total"])
    ]

    # ── Bottleneck stage (most SLA-breached tasks) ───────────────────────────
    overdue_raw = (
        db.table("case_tasks")
        .select("stage_code")
        .eq("sla_breached", True)
        .not_.in_("status", ["completed", "waived"])
        .execute()
    )
    stage_overdue: Counter[str] = Counter(t["stage_code"] for t in overdue_raw.data)
    bottleneck: dict | None = None
    if stage_overdue:
        top_code, top_count = stage_overdue.most_common(1)[0]
        bottleneck = {
            "stage_code": top_code,
            "stage_name": _STAGE_NAMES.get(top_code, top_code),
            "overdue_count": top_count,
        }

    # ── Agent activity ────────────────────────────────────────────────────────
    runs_result = (
        db.table("agent_runs").select("id", count="exact").execute()
    )
    drafted_result = (
        db.table("agent_actions").select("id", count="exact").execute()
    )
    executed_result = (
        db.table("agent_actions")
        .select("id", count="exact")
        .eq("status", "executed")
        .execute()
    )
    pending_result = (
        db.table("agent_actions")
        .select("id", count="exact")
        .eq("status", "pending_approval")
        .execute()
    )

    return {
        "cases": {
            "active": status_counts.get("active", 0),
            "completed": status_counts.get("completed", 0),
            "on_hold": status_counts.get("on_hold", 0),
            "cancelled": status_counts.get("cancelled", 0),
            "total": len(cases),
        },
        "avg_duration_days": avg_duration,
        "bottleneck_stage": bottleneck,
        "by_department": by_department,
        "agent": {
            "total_runs": runs_result.count or 0,
            "actions_drafted": drafted_result.count or 0,
            "actions_executed": executed_result.count or 0,
            "actions_pending": pending_result.count or 0,
        },
    }
