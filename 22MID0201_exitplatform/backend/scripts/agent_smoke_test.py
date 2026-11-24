"""Exercise the compiled supervisor + worker graph directly, bypassing
the not-yet-built `/agent/chat` endpoint.

Signs in as a real seeded employee (same pattern as verify_rls.py /
verify_api.py) to get a genuine RLS-bound ActorContext, then invokes
build_graph() with canned prompts that route to different workers. Prints
which workers were dispatched (active_worker / worker_history) per turn.

Expected outcomes:
  "What's left before my last day?"      -> faq_chatbot
  "Summarize my exit interview"          -> interview_summarizer
  "Any SLA risks on my team's cases?"   -> sla_escalation / dashboard_insights

Either a real model reply or a clean LLMConfigError is a pass — the point is
proving the graph shape (supervisor dispatch, worker routing, tool defense,
checkpoint round-trip) works independently of the model being unblocked.

Run twice on the same thread to verify checkpoint resumption:
    python scripts/agent_smoke_test.py
    python scripts/agent_smoke_test.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.graph import build_graph  # noqa: E402
from app.agent.llm import LLMConfigError  # noqa: E402
from app.agent.state import AgentContext  # noqa: E402
from app.deps import ActorContext  # noqa: E402

DEMO_EMAIL = "kirthana.mekala@example.com"
DEMO_PASSWORD = "ExitDemo!2026"

CANNED_PROMPTS = [
    "What's left before my last day?",
    "Summarize my exit interview",
    "Are there any SLA risks across the team's cases?",
]


def actor_for(email: str, url: str, anon_key: str) -> ActorContext:
    db = create_client(url, anon_key)
    db.auth.sign_in_with_password({"email": email, "password": DEMO_PASSWORD})
    row = (
        db.table("employees")
        .select("id, auth_user_id, full_name, work_email, app_role")
        .eq("work_email", email)
        .limit(1)
        .execute()
        .data[0]
    )
    return ActorContext(
        employee_id=row["id"],
        auth_user_id=row["auth_user_id"],
        role=row["app_role"],
        full_name=row["full_name"],
        email=row["work_email"],
        db=db,
    )


def run_prompt(graph, context: AgentContext, prompt: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"PROMPT: {prompt!r}")
    print(f"thread_id: {context.thread_id!r}")
    print("=" * 60)

    config = {"configurable": {"thread_id": context.thread_id}}
    state_in = {
        "messages": [{"role": "user", "content": prompt}],
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

    try:
        result = graph.invoke(state_in, config=config, context=context)
    except LLMConfigError as exc:
        print(f"LLMConfigError (expected while gateway blocks the model): {exc}")
        return

    if result.get("error"):
        print(f"Run finished with error: {result['error']}")
        return

    usage = result.get("usage") or {}
    history = result.get("worker_history") or []
    messages = result.get("messages") or []

    print(f"Workers dispatched: {[h['worker'] for h in history] or ['(none — direct finish)']}")
    print(f"Iterations:        {result.get('iterations', 0)}")
    print(f"Usage:             {usage}")
    print(f"Worker history:    {json.dumps(history, indent=2)}")

    # Last assistant message is the final reply
    replies = [m for m in messages if m.get("role") == "assistant"]
    if replies:
        last = replies[-1]
        content = last.get("content")
        if isinstance(content, list):
            # content_blocks form — extract text blocks
            text = " ".join(b.get("text", "") for b in content if b.get("type") == "text")
        else:
            text = content or ""
        print(f"\nReply: {text[:500]}")


def main() -> int:
    load_dotenv(ROOT / "backend" / ".env")
    url = os.environ.get("SUPABASE_URL", "")
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not anon_key:
        print("SUPABASE_URL / SUPABASE_ANON_KEY not set in backend/.env.")
        return 1

    actor = actor_for(DEMO_EMAIL, url, anon_key)
    context = AgentContext(actor=actor, trigger="chat", case_id=None)

    try:
        graph = build_graph()
    except RuntimeError as exc:
        print(f"Could not build the graph: {exc}")
        return 1

    for prompt in CANNED_PROMPTS:
        run_prompt(graph, context, prompt)

    print("\n\nAll prompts done. Re-run this script to verify checkpoint resumption.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
