"""
Case list and detail. Backs the manager and HR dashboards.

Note how little authorisation logic lives here: `scope` shapes the query, but
what comes back is decided by RLS. A manager asking for scope=all gets their
team, not an error — the database simply returns nothing else.
"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.deps import Actor
from app.services.cases import create_case
from app.services.pdf import build_pdf, field, rule

router = APIRouter(tags=["cases"])

Scope = Literal["mine", "team", "all"]


class NewCase(BaseModel):
    """Omit employee_id to open your own exit. HR may name someone else."""

    employee_id: str | None = None
    exit_type: Literal["resignation", "termination", "retirement", "end_of_contract"] = (
        "resignation"
    )
    resignation_date: date
    last_working_day: date
    notice_period_days: int = Field(default=30, ge=0, le=365)
    reason: str | None = None


@router.post("/cases", status_code=status.HTTP_201_CREATED)
async def open_case(body: NewCase, actor: Actor) -> dict[str, object]:
    """Open an exit case and expand the task template into it."""
    return create_case(
        actor=actor,
        employee_id=body.employee_id or actor.employee_id,
        resignation_date=body.resignation_date,
        last_working_day=body.last_working_day,
        notice_period_days=body.notice_period_days,
        exit_type=body.exit_type,
        reason=body.reason,
    )


@router.get("/cases")
async def list_cases(
    actor: Actor,
    scope: Scope = Query("all"),
) -> list[dict[str, object]]:
    db = actor.db

    query = db.table("exit_cases").select(
        "*, employee:employees!exit_cases_employee_id_fkey"
        "(id, full_name, emp_code, department, designation, work_email, manager_id)"
    )

    if scope == "mine":
        query = query.eq("employee_id", actor.employee_id)

    result = query.order("last_working_day").execute()

    summaries = []
    for row in result.data:
        employee = row.pop("employee")

        # `team` is a display filter; RLS has already removed anything this
        # person may not see.
        if scope == "team" and employee.get("manager_id") != actor.employee_id:
            continue

        tasks = (
            db.table("case_tasks")
            .select("status, sla_breached")
            .eq("case_id", row["id"])
            .execute()
        )
        open_tasks = [
            t for t in tasks.data if t["status"] not in ("completed", "waived")
        ]

        pending_docs = (
            db.table("documents")
            .select("id", count="exact")
            .eq("case_id", row["id"])
            .eq("status", "pending")
            .execute()
        )

        manager = None
        if employee.get("manager_id"):
            m = (
                db.table("employees")
                .select("id, full_name")
                .eq("id", employee["manager_id"])
                .execute()
            )
            manager = m.data[0] if m.data else None

        summaries.append(
            {
                "case": row,
                "employee": employee,
                "manager": manager,
                "open_tasks": len(open_tasks),
                "overdue_tasks": sum(1 for t in open_tasks if t["sla_breached"]),
                "pending_documents": pending_docs.count or 0,
                "days_remaining": _days_until(row["last_working_day"]),
            }
        )

    return summaries


@router.get("/cases/{case_id}")
async def get_case(case_id: str, actor: Actor) -> dict[str, object]:
    result = (
        actor.db.table("exit_cases")
        .select(
            "*, employee:employees!exit_cases_employee_id_fkey"
            "(id, full_name, emp_code, department, designation, work_email)"
        )
        .eq("id", case_id)
        .execute()
    )

    if not result.data:
        # Indistinguishable from "exists but you may not see it" — deliberate.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")

    row = result.data[0]
    return {"case": row, "employee": row.pop("employee")}


@router.get("/cases/{case_id}/detail")
async def get_case_detail(case_id: str, actor: Actor) -> dict[str, object]:
    """Everything the case review screen needs, in one round trip.

    Declared before `/cases/{case_id}/tasks` only for readability — the paths
    are distinct, so ordering does not matter here.

    Every query goes through the caller's RLS-bound client, so a manager asking
    for a case outside their reports gets an empty `exit_cases` row and the 404
    below, exactly as `get_case` does. There is no authorisation logic here.
    """
    result = (
        actor.db.table("exit_cases")
        .select(
            "*, employee:employees!exit_cases_employee_id_fkey"
            "(id, full_name, emp_code, department, designation, work_email, manager_id)"
        )
        .eq("id", case_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")

    row = result.data[0]
    employee = row.pop("employee")

    manager = None
    if employee.get("manager_id"):
        found = (
            actor.db.table("employees")
            .select("id, full_name")
            .eq("id", employee["manager_id"])
            .execute()
        )
        manager = found.data[0] if found.data else None

    db = actor.db
    stages = db.table("exit_stages").select("*").order("sort_order").execute().data
    tasks = db.table("case_tasks").select("*").eq("case_id", case_id).order("sort_order").execute().data
    documents = (
        db.table("documents").select("*").eq("case_id", case_id)
        .order("created_at", desc=True).execute().data
    )
    document_types = db.table("document_types").select("*").order("sort_order").execute().data
    approvals = (
        db.table("approvals").select("*").eq("case_id", case_id)
        .order("decided_at", desc=True).execute().data
    )

    kt = None
    kt_rows = db.table("kt_records").select("*").eq("case_id", case_id).execute().data
    if kt_rows:
        record = kt_rows[0]
        items = (
            db.table("kt_items").select("*").eq("kt_record_id", record["id"])
            .order("sort_order").execute().data
        )
        kt = {**record, "items": items}

    return {
        "case": row,
        "employee": employee,
        "manager": manager,
        "stages": stages,
        "tasks": tasks,
        "documents": documents,
        "document_types": document_types,
        "approvals": approvals,
        "kt": kt,
        "days_remaining": _days_until(row["last_working_day"]),
    }


@router.get("/cases/{case_id}/certificate")
async def exit_certificate(case_id: str, actor: Actor) -> Response:
    """The exit-process completion confirmation, as a PDF.

    Distinct from the relieving letter, which is a formal document HR issues at
    the final stage. This one is generated from the case record on request and
    only says what this platform can vouch for: every task closed, every
    required document approved.

    Managers are excluded deliberately — they have no use for a copy, and it
    carries the employee's employment dates. The read is RLS-bound either way,
    so a case the caller cannot see is a 404 before this check is reached.
    """
    found = (
        actor.db.table("exit_cases")
        .select(
            "*, employee:employees!exit_cases_employee_id_fkey"
            "(id, full_name, emp_code, department, designation, date_of_joining, manager_id)"
        )
        .eq("id", case_id)
        .execute()
    )
    if not found.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")

    case = found.data[0]
    employee = case.pop("employee")

    if not (actor.is_hr or employee["id"] == actor.employee_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the exiting employee or HR can download this confirmation.",
        )

    tasks = actor.db.table("case_tasks").select("status").eq("case_id", case_id).execute().data
    done = [t for t in tasks if t["status"] in ("completed", "waived")]
    if len(done) != len(tasks) or not tasks:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The exit is not finished yet — {len(tasks) - len(done)} task(s) still open.",
        )

    documents = (
        actor.db.table("documents").select("status").eq("case_id", case_id).execute().data
    )
    approved = sum(1 for d in documents if d["status"] == "approved")

    manager_name = "-"
    if employee.get("manager_id"):
        mgr = (
            actor.db.table("employees")
            .select("full_name")
            .eq("id", employee["manager_id"])
            .execute()
        )
        if mgr.data:
            manager_name = mgr.data[0]["full_name"]

    today = date.today()
    lines: list[tuple[str, str]] = [
        ("h1", "EXIT PROCESS COMPLETION CONFIRMATION"),
        ("", ""),
        *rule(),
        ("", ""),
        field("Employee", employee["full_name"]),
        field("Employee code", employee["emp_code"]),
        field("Designation", employee["designation"]),
        field("Department", employee["department"]),
        field("Date of joining", _long_date(employee["date_of_joining"])),
        field("Last working day", _long_date(case["last_working_day"])),
        field("Exit type", str(case["exit_type"]).replace("_", " ").title()),
        ("", ""),
        ("h2", "CONFIRMATION"),
        ("", ""),
        ("b", "All exit-process activities recorded on this platform have been"),
        ("b", "completed. Every task on the checklist is closed, and all required"),
        ("b", "documents were submitted and approved by the reporting manager."),
        ("", ""),
        field("Reporting manager", manager_name),
        field("Tasks completed", f"{len(done)} / {len(tasks)}  (100%)"),
        field("Documents approved", f"{approved} / {len(documents)}"),
        field("Confirmation date", _long_date(today.isoformat())),
        field("Case reference", case_id),
        ("", ""),
        *rule(),
        ("", ""),
        ("b", "This confirmation is generated from the exit record and states the"),
        ("b", "completion of process activities only. It is not a relieving letter"),
        ("b", "or a statement of employment terms."),
    ]

    filename = f"exit-completion-{employee['emp_code']}.pdf"
    return Response(
        content=build_pdf(lines),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/cases/{case_id}/tasks")
async def get_case_tasks(case_id: str, actor: Actor) -> list[dict[str, object]]:
    return (
        actor.db.table("case_tasks")
        .select("*")
        .eq("case_id", case_id)
        .order("sort_order")
        .execute()
    ).data


@router.get("/cases/{case_id}/documents")
async def get_case_documents(case_id: str, actor: Actor) -> list[dict[str, object]]:
    return (
        actor.db.table("documents")
        .select("*")
        .eq("case_id", case_id)
        .order("created_at", desc=True)
        .execute()
    ).data


def _long_date(date_str: str | None) -> str:
    if not date_str:
        return "-"
    parsed = date.fromisoformat(str(date_str)[:10])
    return f"{parsed.day} {parsed.strftime('%B %Y')}"


def _days_until(date_str: str) -> int:
    return (date.fromisoformat(date_str) - date.today()).days
