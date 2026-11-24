"""
Case creation.

Opening an exit is the one operation that writes to five tables at once, so it
lives here rather than in a handler. The important part is expanding
`task_templates` into real `case_tasks`: a case with no checklist is useless,
and the employee dashboard is empty until this runs.

Due dates are clamped to the last working day — a template offset of 42 days on
a 30-day notice period would otherwise produce tasks due after the person has
gone.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import HTTPException, status

from app.deps import ActorContext, service_db
from app.services.audit import write_audit
from app.services.clearance import open_clearance_detail

FIRST_STAGE = "RESIGNATION_SUBMITTED"


def _employee_row(employee_id: str) -> dict:
    """Department and designation decide which assets and systems this person
    is likely to hold. Read with the service role — the caller may be HR
    opening someone else's exit, and this is a system read, not theirs."""
    found = (
        service_db()
        .table("employees")
        .select("id, department, designation")
        .eq("id", employee_id)
        .limit(1)
        .execute()
    )
    return found.data[0] if found.data else {}


def create_case(
    *,
    actor: ActorContext,
    employee_id: str,
    resignation_date: date,
    last_working_day: date,
    notice_period_days: int,
    exit_type: str = "resignation",
    reason: str | None = None,
) -> dict:
    """Open an exit case and expand the task template into it."""
    db = actor.db

    if last_working_day < resignation_date:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The last working day cannot be before the resignation date.",
        )

    # An employee opens their own; HR opens anyone's. A manager cannot resign on
    # someone's behalf — that is HR's job, and the RLS insert policy agrees.
    if employee_id != actor.employee_id and not actor.is_hr:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only HR can open an exit on someone else's behalf.",
        )

    existing = (
        db.table("exit_cases")
        .select("id")
        .eq("employee_id", employee_id)
        .in_("status", ["draft", "active", "on_hold"])
        .execute()
    )
    if existing.data:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This person already has an exit in progress.",
        )

    created = (
        db.table("exit_cases")
        .insert(
            {
                "employee_id": employee_id,
                "exit_type": exit_type,
                "reason": reason,
                "resignation_date": resignation_date.isoformat(),
                "last_working_day": last_working_day.isoformat(),
                "notice_period_days": notice_period_days,
                "current_stage": FIRST_STAGE,
                "status": "active",
                "created_by": actor.employee_id,
            }
        )
        .execute()
    )
    if not created.data:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You cannot open an exit for this person."
        )

    exit_case = created.data[0]
    case_id = exit_case["id"]

    # Each call below is its own transaction — PostgREST cannot span one across
    # requests — so a failure part-way leaves a case with no checklist. That is
    # worse than no case at all: it blocks the person from retrying, because
    # `exit_cases_one_open_per_employee` then reports one already in progress.
    # So compensate explicitly.
    #
    # The durable fix is a single Postgres function doing all four inserts in
    # one transaction. Worth doing before the pilot carries real volume.
    try:
        expand_template(actor, case_id, employee_id, resignation_date, last_working_day)
        open_knowledge_transfer(actor, case_id)
        open_clearance_detail(case_id, _employee_row(employee_id))
    except Exception:
        service_db().table("exit_cases").delete().eq("id", case_id).execute()
        raise

    write_audit(
        action="exit_cases.created",
        entity_table="exit_cases",
        entity_id=case_id,
        actor=actor,
        case_id=case_id,
        after={
            "employee_id": employee_id,
            "resignation_date": resignation_date.isoformat(),
            "last_working_day": last_working_day.isoformat(),
            "exit_type": exit_type,
        },
    )

    return exit_case


def expand_template(
    actor: ActorContext,
    case_id: str,
    employee_id: str,
    resignation_date: date,
    last_working_day: date,
) -> int:
    """Turn every active task template into a task on this case.

    Writes with the service role, deliberately. These rows are system-generated
    from `task_templates` — the user supplied only dates — and the policies
    correctly forbid the two people who legitimately open cases from writing
    them:

      * `case_tasks_insert` requires can_act_on_case, which excludes the
        exiting employee. They complete tasks; they do not author them.
      * `exit_interviews_write` requires you to BE the case subject, so HR
        opening a case on someone's behalf could not create the interview.

    Loosening either policy to accommodate this would hand users a write they
    should never have. Authorisation already happened: the caller got through
    the RLS-protected insert into `exit_cases` above, or we would not be here.
    """
    templates = (
        actor.db.table("task_templates")
        .select("*")
        .eq("is_active", True)
        .order("sort_order")
        .execute()
    ).data

    rows = []
    for template in templates:
        due = resignation_date + timedelta(days=template["offset_days"])
        rows.append(
            {
                "case_id": case_id,
                "stage_code": template["stage_code"],
                "template_id": template["id"],
                "title": template["title"],
                "description": template["description"],
                "owner_role": template["owner_role"],
                # Only the employee's own tasks get an assignee. IT/Finance/Admin
                # work is role-owned; nobody is named until someone picks it up.
                "assignee_id": employee_id if template["owner_role"] == "employee" else None,
                "doc_type_code": template["doc_type_code"],
                "due_date": min(due, last_working_day).isoformat(),
                "sort_order": template["sort_order"],
                "origin": "template",
            }
        )

    if rows:
        service_db().table("case_tasks").insert(rows).execute()
    return len(rows)


def open_knowledge_transfer(actor: ActorContext, case_id: str) -> None:
    """Create the empty KT record and interview so the employee has a form.

    Service role for the reason given in `expand_template`.
    """
    service_db().table("kt_records").insert(
        {"case_id": case_id, "overall_status": "not_started"}
    ).execute()
    service_db().table("exit_interviews").insert({"case_id": case_id}).execute()
