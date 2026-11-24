"""
Reminders and the notification bell.

The reminder flow here is manual: a human sees an overdue task, reviews a
pre-filled message, edits it, sends it. Phase 4's agent will draft into this
same mechanism rather than growing its own — which keeps one send path, one
audit shape, and a platform that still works with the agent switched off.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.deps import Actor, service_db
from app.services.audit import write_audit
from app.services.email import Message, get_sender

router = APIRouter(tags=["notifications"])


class ReminderBody(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)


@router.get("/tasks/{task_id}/reminder-draft")
async def reminder_draft(task_id: str, actor: Actor) -> dict[str, object]:
    """Pre-fill a reminder so the sender edits rather than composes.

    Deliberately specific: names the task, how late it is, and what it blocks.
    A reminder that says "you have an overdue task" gets ignored.
    """
    task, case, recipient = _load(task_id, actor)

    days_left = (date.fromisoformat(case["last_working_day"]) - date.today()).days
    overdue = (
        (date.today() - date.fromisoformat(task["due_date"])).days
        if task["due_date"]
        else 0
    )

    lateness = (
        f"{overdue} days past its due date"
        if overdue > 1
        else "past its due date"
        if overdue == 1
        else "due today"
    )

    body = (
        f"Hi {recipient['full_name'].split()[0]},\n\n"
        f'"{task["title"]}" is {lateness}.\n\n'
        f"Your last working day is in {days_left} days, and this needs to be "
        f"cleared before the {case['stage_name']} stage can close.\n\n"
        "If something is blocking you, reply and let me know.\n\n"
        f"{actor.full_name}"
    )

    return {
        "task_id": task_id,
        "recipient": {
            "id": recipient["id"],
            "full_name": recipient["full_name"],
            "work_email": recipient["work_email"],
        },
        "subject": f"Overdue: {task['title']}",
        "body": body,
        "days_overdue": overdue,
    }


@router.post("/tasks/{task_id}/remind", status_code=status.HTTP_204_NO_CONTENT)
async def send_reminder(task_id: str, body: ReminderBody, actor: Actor) -> None:
    if actor.role == "employee":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only a manager or HR can send a reminder."
        )

    task, case, recipient = _load(task_id, actor)

    # Notifications are service-role writes: a user must not be able to post
    # into someone else's bell, and `authenticated` has no insert policy.
    service_db().table("notifications").insert(
        {
            "recipient_id": recipient["id"],
            "case_id": task["case_id"],
            "title": body.subject,
            "body": body.body,
        }
    ).execute()

    # Phase 8 makes this a real send. Until then it is recorded, not delivered —
    # the in-app notification above is what the person actually sees.
    get_sender().send(
        Message(to=recipient["work_email"], subject=body.subject, body=body.body)
    )

    write_audit(
        action="tasks.reminder_sent",
        entity_table="case_tasks",
        entity_id=task_id,
        actor=actor,
        case_id=task["case_id"],
        after={"recipient_id": recipient["id"], "subject": body.subject},
    )


@router.get("/notifications")
async def list_notifications(actor: Actor, unread_only: bool = False) -> list[dict]:
    query = (
        actor.db.table("notifications")
        .select("*")
        .order("created_at", desc=True)
        .limit(50)
    )
    if unread_only:
        query = query.is_("read_at", "null")
    return query.execute().data


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(notification_id: str, actor: Actor) -> None:
    actor.db.table("notifications").update(
        {"read_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", notification_id).execute()


# ---------------------------------------------------------------------------


def _load(task_id: str, actor: Actor) -> tuple[dict, dict, dict]:
    """Fetch task, case (with stage name), and the person to chase.

    Everything goes through the RLS-bound client, so a task on a case the actor
    cannot see simply is not found.
    """
    tasks = actor.db.table("case_tasks").select("*").eq("id", task_id).execute()
    if not tasks.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found.")
    task = tasks.data[0]

    cases = (
        actor.db.table("exit_cases")
        .select(
            "*, employee:employees!exit_cases_employee_id_fkey"
            "(id, full_name, work_email, manager_id)"
        )
        .eq("id", task["case_id"])
        .execute()
    )
    if not cases.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")
    case = cases.data[0]

    stage = (
        actor.db.table("exit_stages")
        .select("name")
        .eq("code", task["stage_code"])
        .execute()
    )
    case["stage_name"] = stage.data[0]["name"] if stage.data else task["stage_code"]

    # Chase whoever the task actually belongs to: the assignee if named,
    # otherwise the exiting employee for their own work, otherwise the manager.
    recipient = case["employee"]
    if task["assignee_id"] and task["assignee_id"] != recipient["id"]:
        named = (
            actor.db.table("employees")
            .select("id, full_name, work_email")
            .eq("id", task["assignee_id"])
            .execute()
        )
        if named.data:
            recipient = named.data[0]
    elif task["owner_role"] != "employee" and recipient.get("manager_id"):
        manager = (
            actor.db.table("employees")
            .select("id, full_name, work_email")
            .eq("id", recipient["manager_id"])
            .execute()
        )
        if manager.data:
            recipient = manager.data[0]

    return task, case, recipient
