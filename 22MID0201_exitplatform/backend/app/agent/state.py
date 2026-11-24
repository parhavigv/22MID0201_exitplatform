"""Agent state and per-invocation context.

Split deliberately:

- `AgentState` is what `PostgresSaver` persists to Postgres on every step of
  a run.
- `AgentContext` is LangGraph's `context_schema` — passed once per
  invocation via `.invoke(..., context=...)`, read inside nodes with
  `langgraph.runtime.get_runtime(AgentContext).context`, and never
  checkpointed.

That split isn't cosmetic: `AgentContext.actor.db` is a live, RLS-bound
Supabase client (`app.deps.ActorContext`) built fresh from the caller's JWT.
It must never be serialized into the checkpoint tables — putting it in
`AgentState` would either crash the checkpointer's serializer or, worse,
"succeed" by pickling something that shouldn't outlive the request.

Messages are kept as plain Anthropic-wire-format dicts
(`{"role": "user" | "assistant" | "tool", "content": ...}`), not LangChain
message objects. This build calls the `anthropic` SDK directly — per
CLAUDE.md, "a LangGraph node is just a function and does not need a
LangChain model object".

Increment-2 additions (multi-agent supervisor):
- `active_worker`: which worker key is currently dispatched (None = supervisor turn)
- `worker_history`: list of completed worker runs this turn — written by
  finalize into agent_runs.worker_history (jsonb column, migration 0004)
- `iterations`: how many times the supervisor has routed; loop guard in
  graph.py forces finish after 8 iterations to cap cost
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from app.deps import ActorContext


class AgentState(TypedDict):
    messages: list[dict[str, Any]]
    run_id: str | None
    """Set by load_context once the agent_runs row exists; read by finalize."""
    usage: dict[str, int] | None
    error: str | None
    pending_tool_calls: list[dict[str, Any]]

    # --- Increment-2: multi-agent supervisor fields ---
    active_worker: str | None
    """The WORKER_REGISTRY key of the currently-dispatched worker, or None
    when control is at the supervisor."""
    worker_messages: list[dict[str, Any]]
    """The dispatched worker's own transcript, kept apart from `messages`.

    A worker's turns must not land in the supervisor's transcript. When they
    did, the worker's answer reached the supervisor as a `user` message, and
    the supervisor — correctly, per rule 3 — refused it as something claiming
    to be a worker result. Keeping the threads separate means the answer comes
    back the one way the supervisor already trusts: as the `tool_result` for
    its own `route_to_agent` call."""
    route_call_id: str | None
    """tool_use id of the in-flight `route_to_agent` call, so the worker's
    result can be attached to it. Every tool_use needs its tool_result."""
    worker_history: list[dict[str, Any]]
    """Appended each time a worker finishes — {worker, status, tokens, tools}.
    Written to agent_runs.worker_history (jsonb) in finalize."""
    tool_trace: list[dict[str, Any]]
    """Tool calls made by the worker currently dispatched, drained into that
    worker's `worker_history` entry when it finishes.

    Each entry records the tool, its arguments, a truncated result, and whether
    the call merely drafted. That is what lets a reader check an answer: the
    figure in the reply sits under the call that returned it, so a claim with
    no tool behind it is visible as such."""
    iterations: int
    """Supervisor loop counter. Forced to finish once this exceeds MAX_ITERATIONS."""


@dataclass(frozen=True)
class AgentContext:
    """Per-invocation context — see module docstring. Never persisted."""

    actor: ActorContext
    trigger: Literal["chat", "sweep"]
    case_id: str | None = None

    @property
    def thread_id(self) -> str:
        """Checkpointer thread id, and the same value agent_runs.thread_id
        gets — kept as one property so the two can't drift apart."""
        scope = self.case_id or self.actor.employee_id
        return f"{self.trigger}:{scope}"
