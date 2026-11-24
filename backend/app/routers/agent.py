"""Agent action queue and chat endpoint.

GET  /agent/actions                    — list pending (or any status) actions
POST /agent/actions/{id}/decide        — approve or reject with an optional
                                         edited payload and a decision note
POST /agent/chat                       — SSE chat with the Exit Copilot

RLS note: agent_actions rows are inserted via service_db() by draft tools, so
they bypass RLS on write. On read, RLS lets HR see all rows; managers see only
rows whose case targets their direct reports (see 0002_rls.sql). The POST
/decide endpoint is write-only via service_db — no row-level bypass for reads.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi import status as http_status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.deps import Actor, service_db
from app.services.audit import write_audit

router = APIRouter(tags=["agent"])


# ---------------------------------------------------------------------------
# Chat — SSE streaming
# ---------------------------------------------------------------------------


class ChatBody(BaseModel):
    message: str
    case_id: str | None = None


def _default_case_id(actor: Actor) -> str | None:
    """The case the caller is implicitly asking about when they don't name one.

    An exiting employee has at most one open case (enforced by
    exit_cases_one_open_per_employee), and "what's left before my last day?"
    means that case. Without this the agent has no case in context and tells
    the employee it can't find their own exit — the query is RLS-bound, so it
    can only ever resolve a case the caller is already allowed to read.
    Managers and HR span many cases, so they must name one.
    """
    if actor.role != "employee":
        return None
    result = (
        actor.db.table("exit_cases")
        .select("id")
        .eq("employee_id", actor.employee_id)
        .in_("status", ["draft", "active", "on_hold"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0]["id"] if result.data else None


@router.post("/agent/chat")
async def agent_chat(body: ChatBody, actor: Actor) -> StreamingResponse:
    """Run the Exit Copilot graph and stream the reply as SSE.

    Uses the caller's RLS-bound client (rule 1). The graph itself enforces
    rules 2-4. Runs graph.invoke in a thread pool to avoid blocking the
    event loop — the graph is synchronous (anthropic SDK).
    """
    from app.agent.graph import build_graph  # late import — graph init is heavy
    from app.agent.llm import LLMConfigError
    from app.agent.state import AgentContext

    case_id = body.case_id or _default_case_id(actor)
    context = AgentContext(actor=actor, trigger="chat", case_id=case_id)

    async def event_stream():
        try:
            graph = build_graph()
            config = {"configurable": {"thread_id": context.thread_id}}
            state_in: dict[str, Any] = {
                "messages": [{"role": "user", "content": body.message}],
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

            result: dict[str, Any] = await asyncio.to_thread(
                graph.invoke, state_in, config=config, context=context
            )

            if result.get("error"):
                reply = f"The assistant encountered an error: {result['error']}"
            else:
                messages = result.get("messages") or []
                replies = [m for m in messages if m.get("role") == "assistant"]
                if replies:
                    last = replies[-1]
                    content = last.get("content")
                    if isinstance(content, list):
                        reply = "\n".join(
                            b.get("text", "") for b in content if b.get("type") == "text"
                        )
                    else:
                        reply = content or ""
                else:
                    reply = "I finished thinking but produced no text reply. Please try again."

        except LLMConfigError as exc:
            reply = f"The assistant model is not available right now. ({exc})"
        except Exception as exc:  # noqa: BLE001
            reply = f"An unexpected error occurred: {exc}"

        # Send as a single SSE event. Inline newlines would break the SSE
        # framing (each \n\n is an event boundary), so we join paragraphs
        # with a double space. Future token-level streaming can send word
        # chunks without this normalization.
        reply_safe = "  ".join(para for para in reply.split("\n") if para.strip())
        yield f"data: {reply_safe}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Approval queue
# ---------------------------------------------------------------------------


class DecideBody(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = None
    payload: dict | None = None  # human-edited payload, replaces original


@router.get("/agent/sweep-summary")
async def sweep_summary(actor: Actor) -> dict:
    """Last sweep run info + pending action count — for the HR progress panel."""
    if actor.role == "employee":
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, "HR and managers only.")

    db = service_db()

    last_run = (
        db.table("agent_runs")
        .select("id, status, finished_at, input_tokens, output_tokens, error")
        .eq("trigger", "sweep")
        .order("finished_at", desc=True)
        .limit(1)
        .execute()
    )

    pending = (
        db.table("agent_actions")
        .select("id", count="exact")
        .eq("status", "pending_approval")
        .execute()
    )

    return {
        "last_run": last_run.data[0] if last_run.data else None,
        "pending_actions": pending.count or 0,
    }


@router.get("/agent/runs")
async def list_agent_runs(
    actor: Actor,
    limit: int = Query(50, le=100),
) -> list[dict]:
    """Recent agent runs, with the tool calls each worker made.

    Open to every role, because `agent_runs_select` already draws the line
    correctly: HR sees everything, anyone sees runs they triggered themselves,
    and a manager sees runs against cases they can read. The HR-only check that
    used to sit here was stricter than the database and hid people's own
    conversations from them — which is exactly the audience for a trace showing
    what the assistant looked at before it answered.
    """
    result = (
        actor.db.table("agent_runs")
        .select(
            "id, thread_id, trigger, actor_role, case_id, status, "
            "input_tokens, output_tokens, error, started_at, finished_at, worker_history"
        )
        .order("started_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


@router.get("/agent/actions")
async def list_agent_actions(
    actor: Actor,
    status: str = Query("pending_approval"),
    case_id: str | None = Query(None),
    kind: str | None = Query(None),
) -> list[dict]:
    """List agent actions. Employees cannot see this queue — HR and managers only.

    status: comma-separated values or 'all' to return every status.
    case_id: filter to a single case.
    kind: filter to a specific action kind (e.g. 'verify_compliance').
    """
    if actor.role == "employee":
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, "Only managers and HR can view the action queue.")

    # Read through the RLS-bound client so the DB's own policies scope results
    # (managers see only their team's cases; HR sees all)
    q = actor.db.table("agent_actions").select("*")

    if status != "all":
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if len(statuses) == 1:
            q = q.eq("status", statuses[0])
        elif statuses:
            q = q.in_("status", statuses)

    if case_id:
        q = q.eq("case_id", case_id)

    if kind:
        q = q.eq("kind", kind)

    result = q.order("created_at", desc=True).limit(100).execute()
    return result.data


@router.post("/agent/actions/{action_id}/decide", status_code=http_status.HTTP_204_NO_CONTENT)
async def decide_agent_action(
    action_id: str, body: DecideBody, actor: Actor, background_tasks: BackgroundTasks
) -> None:
    """Approve or reject an agent-drafted action."""
    if actor.role == "employee":
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, "Only managers and HR can decide on actions.")

    # Read through RLS to confirm this actor can see (and therefore decide on) this action
    existing = actor.db.table("agent_actions").select("*").eq("id", action_id).limit(1).execute()
    if not existing.data:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Action not found.")

    action = existing.data[0]
    if action["status"] != "pending_approval":
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            f"Action is already {action['status']!r} — cannot decide again.",
        )

    now = datetime.now(timezone.utc).isoformat()
    update: dict = {
        "status": body.decision,
        "approver_id": actor.employee_id,
        "decided_at": now,
        "decision_note": body.note,
    }
    if body.payload is not None:
        update["approved_payload"] = body.payload

    # Use service_db() for the write — agent_actions has no insert/update
    # policy for the authenticated role (all writes are system-sourced, same
    # as draft_action() in the tools). This is still a human-authored decision,
    # which is why actor_type='human' goes in the audit row below.
    service_db().table("agent_actions").update(update).eq("id", action_id).execute()

    write_audit(
        action=f"agent_actions.{body.decision}",
        entity_table="agent_actions",
        entity_id=action_id,
        actor=actor,
        actor_type="human",
        case_id=action.get("case_id"),
        before={"status": "pending_approval"},
        after={"status": body.decision, "note": body.note},
    )

    if body.decision == "approved":
        # Fetch the full, possibly-updated action row (approved_payload may have
        # just been written above). Pass to executor in a background task so
        # the 204 goes back before the real effect runs — slow external calls
        # (email, vector search) don't block the approver's UI.
        from app.services.executor import execute  # lazy import — not on hot path

        updated = service_db().table("agent_actions").select("*").eq("id", action_id).limit(1).execute()
        fresh_action = updated.data[0] if updated.data else action
        background_tasks.add_task(execute, fresh_action, actor.employee_id)
