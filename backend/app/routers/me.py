"""The signed-in person's own view. Backs the employee dashboard."""

from fastapi import APIRouter

from app.deps import Actor

router = APIRouter(tags=["me"])


@router.get("/me")
async def get_me(actor: Actor) -> dict[str, object]:
    """Session bootstrap. The frontend's AuthProvider calls this on load.

    Returns the whole employee row — the app shell shows designation and
    department, and screens branch on app_role. Shape matches `Session` in
    frontend/src/lib/types.ts.
    """
    found = (
        actor.db.table("employees")
        .select(
            "id, emp_code, full_name, work_email, department, designation,"
            " date_of_joining, manager_id, app_role, is_active"
        )
        .eq("id", actor.employee_id)
        .single()
        .execute()
    )
    return {"employee": found.data, "role": actor.role}


@router.get("/employees")
async def list_employees(actor: Actor) -> list[dict[str, object]]:
    """Active colleagues, for pickers like successor nomination.

    Scope comes from RLS, not from a filter here: an employee sees themselves
    and their manager, a manager sees their reports, HR sees everyone. That is
    already the right candidate pool — a manager nominating a successor should
    be choosing from their own team.

    Deliberately narrow columns. This is a directory lookup that feeds a
    dropdown, not a profile endpoint, so it returns no dates of joining and no
    role assignments.
    """
    return (
        actor.db.table("employees")
        .select("id, full_name, work_email, department, designation, is_active")
        .eq("is_active", True)
        .order("full_name")
        .execute()
    ).data


@router.get("/me/exit")
async def get_my_exit(actor: Actor) -> dict[str, object] | None:
    """Everything the employee's own dashboard renders, in one request.

    Shape matches `MyExitView` in frontend/src/lib/types.ts.
    """
    db = actor.db

    # An open case first. Failing that, fall back to a completed one so the
    # dashboard does not go blank the moment HR closes the exit — that is
    # exactly when the employee wants the completion confirmation and their
    # certificate, and excluding completed cases meant they could never reach
    # either. Cancelled cases stay hidden: that exit did not happen.
    cases = (
        db.table("exit_cases")
        .select("*")
        .eq("employee_id", actor.employee_id)
        .in_("status", ["draft", "active", "on_hold"])
        .limit(1)
        .execute()
    )

    if not cases.data:
        cases = (
            db.table("exit_cases")
            .select("*")
            .eq("employee_id", actor.employee_id)
            .eq("status", "completed")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

    if not cases.data:
        return None

    exit_case = cases.data[0]
    case_id = exit_case["id"]

    tasks = (
        db.table("case_tasks")
        .select("*")
        .eq("case_id", case_id)
        .order("sort_order")
        .execute()
    )
    documents = db.table("documents").select("*").eq("case_id", case_id).execute()
    stages = db.table("exit_stages").select("*").order("sort_order").execute()
    document_types = db.table("document_types").select("*").order("sort_order").execute()

    manager = None
    employee = (
        db.table("employees")
        .select("manager_id")
        .eq("id", actor.employee_id)
        .single()
        .execute()
    )
    if employee.data and employee.data["manager_id"]:
        m = (
            db.table("employees")
            .select("id, full_name, work_email")
            .eq("id", employee.data["manager_id"])
            .single()
            .execute()
        )
        manager = m.data

    # What IT and Finance are tracking on this person's behalf.
    #
    # Both lists existed but only the staff who work them could see them, so
    # IT was recording that Kirthana still had a MacBook and Kirthana had no
    # way to find that out. RLS already allowed the read — nothing surfaced it.
    #
    # Read-only for the employee: marking a laptop returned stays IT's call,
    # and the settlement is Finance's. This is "what is being tracked about
    # me", not a second place to change it.
    assets = (
        db.table("case_assets")
        .select("id, name, category, identifier, status, returned_at")
        .eq("case_id", case_id)
        .order("sort_order")
        .execute()
    ).data

    settlement = (
        db.table("case_settlement")
        .select("id, kind, label, amount, status, note")
        .eq("case_id", case_id)
        .order("sort_order")
        .execute()
    ).data

    return {
        "case": exit_case,
        "stages": stages.data,
        "tasks": tasks.data,
        "documents": documents.data,
        "document_types": document_types.data,
        "manager": manager,
        "assets": assets,
        "settlement": settlement,
        "days_remaining": _days_until(exit_case["last_working_day"]),
    }


def _days_until(date_str: str) -> int:
    from datetime import date

    return (date.fromisoformat(date_str) - date.today()).days
