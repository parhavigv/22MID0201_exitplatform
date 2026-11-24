"""The agent graph — Phase 3, increment 2: supervisor + 19 worker agents.

Shape (deviation from CLAUDE.md rule 5 — explicitly approved by user):

    load_context -> supervisor ──route_to_agent──> worker_node ──> tool_node
                        ^                               |    ^________|
                        |_____worker returns____________|
                        |
                        └──finish──> finalize

Key design decisions (see the plan file for the full rationale):

- The supervisor is given two tool definitions: `route_to_agent` and `finish`.
  Its tool call IS the routing decision — no new mechanism, just the same
  tool-call plumbing already proven in call_model/LLMResult.

- `worker_node` is ONE function, not 20. It looks up
  WORKER_REGISTRY[state["active_worker"]], calls call_model with that
  worker's prompt and tool subset. A worker is a data row, not a graph node.

- tool_node checks incoming call names against the ACTIVE worker's allowed
  tools tuple before executing — defense against rule-3 prompt injection in
  document/interview text trying to call out-of-remit tools.

- After a worker finishes (no more tool calls), control returns to the
  supervisor (not straight to finalize) so the supervisor can chain another
  worker or call finish.

- Loop guard: past MAX_ITERATIONS supervisor turns, force finish — real cost
  and safety net now that one conversation turn can fan out to multiple LLM
  calls across workers.

- worker_history is appended per worker run and written to
  agent_runs.worker_history (jsonb column, migration 0004) in finalize.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Literal

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import get_runtime
from psycopg import Connection
from psycopg.rows import dict_row

from app.agent.llm import LLMConfigError, LLMResult, call_model
from app.agent.prompts import SUPERVISOR_PROMPT
from app.agent.state import AgentContext, AgentState
from app.agent.tools import TOOL_DEFS_BY_NAME, ToolContext, call_tool
from app.agent.workers import WORKER_REGISTRY
from app.config import get_settings
from app.db import pg_connect_kwargs
from app.deps import service_db

logger = logging.getLogger("app.agent.graph")

MAX_ITERATIONS = 8  # loop guard — force finish after this many supervisor turns


# ---------------------------------------------------------------------------
# Routing tool definitions (given to the supervisor only)
# ---------------------------------------------------------------------------

_WorkerEnum = Enum("_WorkerEnum", {k: k for k in WORKER_REGISTRY})  # type: ignore[misc]

ROUTING_TOOLS = [
    {
        "name": "route_to_agent",
        "description": (
            "Dispatch to a specialist worker. Provide a clear, specific instruction — "
            "the worker cannot see your reasoning, only the instruction and conversation so far."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": list(WORKER_REGISTRY.keys()),
                    "description": "The worker key to route to.",
                },
                "instruction": {
                    "type": "string",
                    "description": "Specific task instruction for the worker.",
                },
            },
            "required": ["agent", "instruction"],
        },
    },
    {
        "name": "finish",
        "description": "Return a final reply to the user. Call this once a worker's result is enough to answer, or for simple questions no worker is needed for.",
        "input_schema": {
            "type": "object",
            "properties": {"reply": {"type": "string"}},
            "required": ["reply"],
        },
    },
]


# ---------------------------------------------------------------------------
# agent_runs bookkeeping
# ---------------------------------------------------------------------------


def _open_run(context: AgentContext) -> str:
    row = (
        service_db()
        .table("agent_runs")
        .insert(
            {
                "thread_id": context.thread_id,
                "trigger": context.trigger,
                "actor_id": context.actor.employee_id,
                "actor_role": context.actor.role,
                "case_id": context.case_id,
                "status": "running",
                "model": get_settings().llm_model or "unknown",
            }
        )
        .execute()
    )
    return row.data[0]["id"]


def _close_run(run_id: str, state: AgentState) -> None:
    update: dict[str, Any] = {"finished_at": "now()"}
    if state.get("error"):
        update["status"] = "failed"
        update["error"] = state["error"][:2000]
    else:
        update["status"] = "completed"
        usage = state.get("usage") or {}
        update["input_tokens"] = usage.get("input_tokens", 0)
        update["output_tokens"] = usage.get("output_tokens", 0)
        update["cache_read_tokens"] = usage.get("cache_read_tokens", 0)
        # Pass the list itself, not json.dumps(it). worker_history is jsonb
        # (migration 0004) and PostgREST serialises the value it is given —
        # handing it a pre-encoded string stored a quoted JSON *string* rather
        # than an array, so readers got text where they expected a list.
        history = state.get("worker_history") or []
        if history:
            update["worker_history"] = history
    service_db().table("agent_runs").update(update).eq("id", run_id).execute()


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def _context_block(context: AgentContext) -> str:
    """Who is asking and which case they are on, appended to the system prompt.

    The case id only ever reached the tools, never the model, so "draft the
    revocation plan for this person" got answered with "which person?" — the
    supervisor had no idea a case was already in scope and asked the user for
    something the platform already knew.

    It goes in the system prompt rather than the transcript on purpose. A
    platform-authored `user` message claiming to supply context is exactly the
    shape of a prompt injection, and the supervisor is right to distrust one;
    the system prompt is not user-supplied, so there is nothing to distrust.
    """
    lines = [
        "",
        "--- Current context ---",
        f"Asked by: {context.actor.full_name} ({context.actor.role})",
    ]

    if not context.case_id:
        lines.append(
            "No specific exit case is in scope. Ask which employee they mean "
            "before routing to a worker that needs one."
        )
        return "\n".join(lines)

    lines.append(f"Exit case in scope: {context.case_id}")
    try:
        found = (
            context.actor.db.table("exit_cases")
            .select(
                "current_stage, last_working_day, status,"
                " employee:employees!exit_cases_employee_id_fkey"
                "(full_name, designation, department)"
            )
            .eq("id", context.case_id)
            .limit(1)
            .execute()
        )
        if found.data:
            row = found.data[0]
            who = row["employee"]
            lines += [
                f"Employee: {who['full_name']} — {who['designation']}, {who['department']}",
                f"Stage: {row['current_stage']} · last working day {row['last_working_day']}"
                f" · case is {row['status']}",
                "Tools default to this case when no case_id is given.",
            ]
    except Exception:  # noqa: BLE001 - context is a convenience, never a hard failure
        logger.warning("load_context: could not summarise case %s", context.case_id)

    return "\n".join(lines)


def load_context(state: AgentState) -> AgentState:
    context = get_runtime(AgentContext).context
    return {
        **state,
        "run_id": _open_run(context),
        "active_worker": None,
        "worker_messages": [],
        "route_call_id": None,
        "tool_trace": [],
        "worker_history": state.get("worker_history") or [],
        "iterations": state.get("iterations") or 0,
    }


def supervisor(state: AgentState) -> AgentState:
    """Reads the conversation and either routes to a worker or finishes."""
    iterations = (state.get("iterations") or 0) + 1

    # Loop guard — don't let a confused run fan out indefinitely
    if iterations > MAX_ITERATIONS:
        logger.warning("supervisor: MAX_ITERATIONS (%d) reached — forcing finish", MAX_ITERATIONS)
        forced_reply = (
            "I've coordinated several steps on this request but haven't been able "
            "to fully resolve it within the allowed number of steps. Please try "
            "rephrasing or break the request into smaller parts."
        )
        return {
            **state,
            "iterations": iterations,
            "active_worker": None,
            "pending_tool_calls": [
                {"id": "forced_finish", "name": "finish", "input": {"reply": forced_reply}}
            ],
        }

    try:
        result: LLMResult = call_model(
            messages=state["messages"],
            system=SUPERVISOR_PROMPT + _context_block(get_runtime(AgentContext).context),
            tools=ROUTING_TOOLS,
        )
    except LLMConfigError as exc:
        logger.error("supervisor: LLM unusable — %s", exc)
        return {**state, "error": str(exc), "iterations": iterations}

    # Append the supervisor's assistant turn (with full content blocks so
    # any tool_use block stays in the transcript)
    new_messages = state["messages"] + [
        {"role": "assistant", "content": result.content_blocks}
    ]

    # Accumulate token usage across supervisor + all worker calls
    prev_usage = state.get("usage") or {}
    usage = {
        "input_tokens": prev_usage.get("input_tokens", 0) + result.input_tokens,
        "output_tokens": prev_usage.get("output_tokens", 0) + result.output_tokens,
        "cache_read_tokens": prev_usage.get("cache_read_tokens", 0) + result.cache_read_tokens,
    }

    return {
        **state,
        "messages": new_messages,
        "pending_tool_calls": result.tool_calls,
        "usage": usage,
        "iterations": iterations,
        "active_worker": None,  # supervisor turn — no worker active yet
    }


def worker_node(state: AgentState) -> AgentState:
    """Generic worker — one function for all 19 workers.

    Looks up the active worker's spec from WORKER_REGISTRY, calls call_model
    with that persona's prompt and tool subset. Returns control to the
    supervisor once the worker has no more tool calls.
    """
    worker_key = state.get("active_worker")
    if not worker_key or worker_key not in WORKER_REGISTRY:
        return {**state, "error": f"Unknown worker key: {worker_key!r}"}

    spec = WORKER_REGISTRY[worker_key]
    tool_defs = [TOOL_DEFS_BY_NAME[t] for t in spec.tools if t in TOOL_DEFS_BY_NAME]

    try:
        result: LLMResult = call_model(
            messages=state["worker_messages"],
            system=spec.prompt + _context_block(get_runtime(AgentContext).context),
            tools=tool_defs or None,
        )
    except LLMConfigError as exc:
        logger.error("worker_node [%s]: LLM unusable — %s", worker_key, exc)
        return {**state, "error": str(exc)}

    worker_messages = state["worker_messages"] + [
        {"role": "assistant", "content": result.content_blocks}
    ]

    prev_usage = state.get("usage") or {}
    usage = {
        "input_tokens": prev_usage.get("input_tokens", 0) + result.input_tokens,
        "output_tokens": prev_usage.get("output_tokens", 0) + result.output_tokens,
        "cache_read_tokens": prev_usage.get("cache_read_tokens", 0) + result.cache_read_tokens,
    }

    # Still calling tools — stay in the worker loop.
    if result.tool_calls:
        return {
            **state,
            "worker_messages": worker_messages,
            "pending_tool_calls": result.tool_calls,
            "usage": usage,
        }

    # Done: close the supervisor's open route_to_agent call with this answer.
    # active_worker stays set so record_worker_done can log the dispatch; that
    # shim is what hands control back to the supervisor.
    return {
        **state,
        "messages": state["messages"] + [
            {
                "role": "tool",
                "tool_use_id": state["route_call_id"],
                "content": result.text or "(the worker returned no text)",
            }
        ],
        "pending_tool_calls": [],
        "usage": usage,
    }


def tool_node(state: AgentState) -> AgentState:
    """Execute pending tool calls — one function used by both supervisor
    (routing tools) and workers (platform tools).

    For worker tool calls: checks the call name is in the ACTIVE worker's
    allowed tools tuple before executing. Anything outside that set is
    refused with a log warning — defense against rule-3 prompt injection
    in document/interview text trying to invoke out-of-remit tools.
    """
    context = get_runtime(AgentContext).context
    worker_key = state.get("active_worker")
    active_spec = WORKER_REGISTRY.get(worker_key) if worker_key else None

    tool_ctx = ToolContext(
        actor=context.actor,
        run_id=state.get("run_id"),
        case_id=context.case_id,
    )

    # Every call is recorded with what it asked for and what came back. This is
    # what makes an answer checkable: a reply saying "2 tasks are overdue" sits
    # directly under the tool call that returned 2, so a reader can see the
    # figure came from the database rather than from the model.
    trace: list[dict[str, Any]] = list(state.get("tool_trace") or [])

    results = []
    for call in state.get("pending_tool_calls") or []:
        name = call["name"]

        # Routing tool calls (route_to_agent / finish) are handled by the
        # graph edges, not executed as platform tool calls — they should never
        # reach tool_node. If they somehow do, return an error rather than
        # silently ignoring them.
        if name in ("route_to_agent", "finish"):
            results.append({
                "role": "tool",
                "tool_use_id": call["id"],
                "content": f"Internal error: routing call {name!r} reached tool_node.",
            })
            continue

        # Defense check: refuse tool calls outside the active worker's remit
        if active_spec and name not in active_spec.tools:
            logger.warning(
                "tool_node: worker %r tried to call %r which is not in its allowed tools %r — refused",
                worker_key, name, active_spec.tools,
            )
            results.append({
                "role": "tool",
                "tool_use_id": call["id"],
                "content": (
                    f"Refused: {name!r} is not an allowed tool for this worker. "
                    "Only use tools listed in your instructions."
                ),
            })
            # A refusal is worth showing: it is the injection defence working,
            # and a reader should see the agent was stopped, not that it complied.
            trace.append({
                "worker": worker_key,
                "tool": name,
                "input": call.get("input") or {},
                "refused": True,
                "result": f"Refused — {name} is not in this worker's tool list.",
            })
            continue

        content = call_tool(name, call.get("input") or {}, tool_ctx)
        results.append({"role": "tool", "tool_use_id": call["id"], "content": content})
        trace.append({
            "worker": worker_key,
            "tool": name,
            "input": call.get("input") or {},
            "refused": False,
            # Truncated: a checklist can run to thousands of characters, and the
            # trace is a receipt, not a second copy of the data. The reader can
            # open the case itself for the full version.
            "result": _summarise(content),
            # Sensitive tools return a draft id rather than performing the
            # change (rule 2). Surfacing that distinction is the point of the
            # "nothing was written" line on the trace.
            "drafted": content.startswith("Drafted ("),
        })

    # Results belong to whichever transcript issued the calls — the worker's
    # own thread while one is dispatched, otherwise the supervisor's.
    if worker_key:
        return {
            **state,
            "tool_trace": trace,
            "worker_messages": state["worker_messages"] + results,
            "pending_tool_calls": [],
        }
    return {
        **state,
        "tool_trace": trace,
        "messages": state["messages"] + results,
        "pending_tool_calls": [],
    }


def _summarise(text: str, limit: int = 400) -> str:
    """One readable line of what a tool returned.

    Tool results are JSON blobs meant for the model, and a trace showing three
    thousand characters of them teaches a reader nothing. Collapse whitespace
    and cut to something a person can scan in a second.
    """
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def finalize(state: AgentState) -> AgentState:
    """Extract the final reply from pending_tool_calls (finish tool call from
    the supervisor), close the agent_run row, and return clean state."""
    # The supervisor's "finish" tool call carries the reply
    final_reply = ""
    for call in state.get("pending_tool_calls") or []:
        if call["name"] == "finish":
            final_reply = call["input"].get("reply", "")
            break

    if final_reply:
        new_messages = state["messages"] + [
            {"role": "assistant", "content": final_reply}
        ]
    else:
        new_messages = state["messages"]

    run_id = state.get("run_id")
    if run_id:
        _close_run(run_id, {**state, "messages": new_messages})

    return {**state, "messages": new_messages, "pending_tool_calls": []}


# ---------------------------------------------------------------------------
# Routing functions (conditional edges)
# ---------------------------------------------------------------------------


def route_after_supervisor(
    state: AgentState,
) -> Literal["worker_node", "tool_node", "finalize"]:
    """Inspect the supervisor's tool call to decide next node."""
    if state.get("error"):
        return "finalize"

    calls = state.get("pending_tool_calls") or []
    if not calls:
        # Supervisor replied in plain text with no tool call — treat as finish
        return "finalize"

    call = calls[0]
    name = call["name"]

    if name == "finish":
        return "finalize"

    if name == "route_to_agent":
        agent_key = call["input"].get("agent", "")
        instruction = call["input"].get("instruction", "")
        if agent_key not in WORKER_REGISTRY:
            logger.warning("supervisor routed to unknown worker %r — finishing", agent_key)
            return "finalize"

        # Inject the routing instruction as a user-turn so the worker sees it
        # at the end of the conversation, then update active_worker in-place.
        # We mutate state here because this is a routing function, not a node —
        # LangGraph reads the return value only for the edge choice.
        # The actual state mutation happens by returning a modified dict from
        # the node, so we store the pending routing decision in pending_tool_calls
        # and let a thin shim node apply it.
        return "worker_node"

    # Unknown tool name from supervisor — go to finalize
    logger.warning("supervisor called unknown tool %r — finishing", name)
    return "finalize"


def _apply_routing(state: AgentState) -> AgentState:
    """Shim node: reads the supervisor's route_to_agent call and sets
    active_worker + injects the instruction into messages, then clears
    pending_tool_calls so worker_node sees a clean slate.

    This is a separate node (not inline in route_after_supervisor) because
    LangGraph routing functions must be pure — they can inspect state but
    must not mutate it.
    """
    calls = state.get("pending_tool_calls") or []
    if not calls or calls[0]["name"] != "route_to_agent":
        return state

    call = calls[0]
    agent_key = call["input"].get("agent", "")
    instruction = call["input"].get("instruction", "")

    # The worker starts its own transcript, seeded with the user's original
    # request plus the supervisor's instruction. The supervisor's own
    # transcript is left untouched — its route_to_agent tool_use stays open
    # until worker_node closes it with the worker's answer as the tool_result.
    original_request = next(
        (m for m in state["messages"] if m.get("role") == "user"),
        {"role": "user", "content": instruction},
    )

    return {
        **state,
        "worker_messages": [
            original_request,
            {"role": "user", "content": f"[Instruction from supervisor] {instruction}"},
        ],
        "pending_tool_calls": [],
        "active_worker": agent_key,
        "route_call_id": call["id"],
    }


def route_after_worker(state: AgentState) -> Literal["tool_node", "supervisor"]:
    """If the worker has tool calls pending, execute them; otherwise return
    to the supervisor to decide next step."""
    if state.get("error"):
        return "supervisor"  # let the supervisor decide how to handle it
    if state.get("pending_tool_calls"):
        return "tool_node"
    return "supervisor"


def route_after_tools(state: AgentState) -> Literal["worker_node", "supervisor"]:
    """After tool_node runs: if active_worker is set, the tools were for a
    worker and we go back to that worker for its next turn. Otherwise the
    tools were routing tools and we're done (finalize is handled elsewhere)."""
    if state.get("active_worker"):
        return "worker_node"
    return "supervisor"


def _record_worker_done(state: AgentState) -> AgentState:
    """Shim node: appended to worker_history when the worker returns to the
    supervisor without any pending tool calls (i.e., worker is done for this
    dispatch)."""
    worker_key = state.get("active_worker")
    if not worker_key:
        return state

    usage = state.get("usage") or {}
    history = list(state.get("worker_history") or [])

    # Hand this worker its own tool calls, so the trace reads as
    # "worker → the reads it made → what came back" rather than one flat list.
    trace = list(state.get("tool_trace") or [])
    mine = [t for t in trace if t.get("worker") == worker_key]
    rest = [t for t in trace if t.get("worker") != worker_key]

    history.append({
        "worker": worker_key,
        "status": "done",
        "tokens": usage.get("output_tokens", 0),
        "tools": mine,
    })

    return {
        **state,
        "worker_history": history,
        "tool_trace": rest,
        "active_worker": None,  # back to supervisor
        "worker_messages": [],  # scratch transcript ends with the dispatch
        "route_call_id": None,
    }


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------


def _long_lived_checkpointer(database_url: str) -> PostgresSaver:
    """Open a persistent connection for the checkpointer.

    PostgresSaver.from_conn_string is a contextmanager that closes the
    connection on exit — wrong for a graph compiled once and invoked many
    times. We open the connection directly and keep it for the process lifetime.
    Supabase passwords routinely contain URI-special chars, so components are
    passed as keywords via pg_connect_kwargs (never the raw URI string).
    """
    conn = Connection.connect(
        **pg_connect_kwargs(database_url),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    return PostgresSaver(conn)


def build_graph() -> CompiledStateGraph:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not set — the checkpointer needs it. "
            "See backend/.env."
        )

    graph = StateGraph(AgentState, context_schema=AgentContext)

    # Nodes
    graph.add_node("load_context", load_context)
    graph.add_node("supervisor", supervisor)
    graph.add_node("apply_routing", _apply_routing)   # shim: set active_worker
    graph.add_node("worker_node", worker_node)
    graph.add_node("tool_node", tool_node)
    graph.add_node("record_worker_done", _record_worker_done)  # shim: append history
    graph.add_node("finalize", finalize)

    # Edges
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "supervisor")

    # Supervisor routes
    graph.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "worker_node": "apply_routing",  # via shim
            "tool_node": "tool_node",        # shouldn't happen; safety valve
            "finalize": "finalize",
        },
    )
    graph.add_edge("apply_routing", "worker_node")

    # Worker loop
    graph.add_conditional_edges(
        "worker_node",
        route_after_worker,
        {
            "tool_node": "tool_node",
            "supervisor": "record_worker_done",  # via shim
        },
    )
    graph.add_edge("record_worker_done", "supervisor")

    # Tool node routes back based on whether a worker is active
    graph.add_conditional_edges(
        "tool_node",
        route_after_tools,
        {
            "worker_node": "worker_node",
            "supervisor": "supervisor",
        },
    )

    graph.add_edge("finalize", END)

    checkpointer = _long_lived_checkpointer(settings.database_url)
    return graph.compile(checkpointer=checkpointer)
