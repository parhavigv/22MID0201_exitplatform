"""The six read tools (execute immediately, no draft/approval step) — CLAUDE.md's
list, one function each. Every query goes through `ctx.actor.db`, the
RLS-bound client from the caller's own JWT (rule 1): a case, task, or
employee row this actor's role wouldn't see in the dashboard is not visible
to the model either, and that's enforced by Postgres, not by anything in
this file choosing not to ask.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.agent.tools.base import (
    ToolContext,
    ToolSpec,
    dump,
    resolve_case_id,
    wrap_untrusted,
)

DONE = ("completed", "waived")
OPEN = ("pending", "in_progress", "blocked")


def get_exit_case(ctx: ToolContext, case_id: str | None = None) -> str:
    cid = resolve_case_id(ctx, case_id)
    if not cid:
        return "No case_id given, and none in context for this turn."

    rows = (
        ctx.actor.db.table("exit_cases")
        .select(
            "id, employee_id, exit_type, resignation_date, last_working_day,"
            " notice_period_days, current_stage, status, risk_score,"
            " employee:employees!exit_cases_employee_id_fkey(id, full_name, department, designation, manager_id)"
        )
        .eq("id", cid)
        .limit(1)
        .execute()
    )
    if not rows.data:
        return f"No case visible for id={cid} — it may not exist, or your access doesn't include it."

    case = rows.data[0]
    tasks = (
        ctx.actor.db.table("case_tasks")
        .select("id, title, stage_code, status, due_date, sla_breached")
        .eq("case_id", cid)
        .order("sort_order")
        .execute()
        .data
    )
    open_tasks = [t for t in tasks if t["status"] not in DONE]
    case["open_tasks"] = len(open_tasks)
    case["overdue_tasks"] = sum(1 for t in open_tasks if t["sla_breached"])
    case["tasks"] = tasks
    return dump(case)


def list_cases(ctx: ToolContext, scope: str = "all") -> str:
    query = ctx.actor.db.table("exit_cases").select(
        "id, current_stage, status, last_working_day, risk_score,"
        " employee:employees!exit_cases_employee_id_fkey(id, full_name, department, manager_id)"
    )
    if scope == "mine":
        query = query.eq("employee_id", ctx.actor.employee_id)
    rows = query.order("last_working_day").execute().data

    summaries: list[dict[str, Any]] = []
    for row in rows:
        employee = row.pop("employee") or {}
        if scope == "team" and employee.get("manager_id") != ctx.actor.employee_id:
            continue
        tasks = (
            ctx.actor.db.table("case_tasks")
            .select("status, sla_breached")
            .eq("case_id", row["id"])
            .execute()
            .data
        )
        open_tasks = [t for t in tasks if t["status"] not in DONE]
        summaries.append(
            {
                **row,
                "employee_name": employee.get("full_name"),
                "department": employee.get("department"),
                "open_tasks": len(open_tasks),
                "overdue_tasks": sum(1 for t in open_tasks if t["sla_breached"]),
            }
        )
    if not summaries:
        return f"No cases visible for scope={scope!r} — RLS may be filtering everything, or none exist."
    return dump(summaries)


def get_checklist(ctx: ToolContext, case_id: str | None = None) -> str:
    cid = resolve_case_id(ctx, case_id)
    if not cid:
        return "No case_id given, and none in context for this turn."
    tasks = (
        ctx.actor.db.table("case_tasks")
        .select("id, title, description, stage_code, owner_role, status, due_date, sla_breached, doc_type_code")
        .eq("case_id", cid)
        .order("sort_order")
        .execute()
        .data
    )
    if not tasks:
        return f"No checklist tasks visible for case {cid}."
    return dump(tasks)


def search_policy_docs(ctx: ToolContext, query: str) -> str:
    """Vector similarity search over embedded policy chunks.

    Embeds the query with the same model used at ingest time (Portkey →
    text-embedding-3-small, 1024-dim) and calls the `search_policy_chunks`
    Postgres function (migration 0005) via RPC.  Falls back to plain ilike
    if the embedding pipeline is unavailable (no PORTKEY_API_KEY, cold
    gateway, etc.) so the tool still returns something useful.
    """
    try:
        from app.services.rag import embed_texts  # late import — heavy client init

        query_embedding = embed_texts([query])[0]
        rows = (
            ctx.actor.db.rpc(
                "search_policy_chunks",
                {"query_embedding": query_embedding, "match_count": 5},
            )
            .execute()
            .data
        )
    except Exception as exc:
        # Embedding unavailable — fall back to text search so the tool still works
        import logging
        logging.getLogger("app.agent.tools.reads").warning(
            "search_policy_docs: vector embed failed (%s), falling back to ilike", exc
        )
        like = f"%{query}%"
        rows = (
            ctx.actor.db.table("policy_chunks")
            .select("chunk_index, heading, content, policy_doc:policy_docs(title, version)")
            .or_(f"content.ilike.{like},heading.ilike.{like}")
            .limit(5)
            .execute()
            .data
        )

    if not rows:
        return (
            "No policy document covers this topic. "
            "Do not guess at an answer — tell the user the policy does not address it."
        )

    # Format results with doc title + version so the model can cite sources
    formatted = []
    for r in rows:
        title = r.get("title") or (r.get("policy_doc") or {}).get("title", "Unknown")
        version = r.get("version") or (r.get("policy_doc") or {}).get("version", "")
        sim = r.get("similarity")
        sim_str = f" (similarity {sim:.2f})" if sim is not None else ""
        formatted.append(
            f"[Source: {title} v{version}{sim_str}]\n"
            f"{r['heading'] if r.get('heading') else ''}\n"
            f"{r['content']}"
        )

    return "\n\n---\n\n".join(formatted)


def get_dashboard_metrics(ctx: ToolContext) -> str:
    cases = (
        ctx.actor.db.table("exit_cases")
        .select("id, current_stage, status")
        .in_("status", ["draft", "active", "on_hold"])
        .execute()
        .data
    )
    if not cases:
        return dump({"open_cases": 0, "by_stage": {}, "tasks_overdue": 0, "documents_pending": 0})

    case_ids = [c["id"] for c in cases]
    by_stage: dict[str, int] = {}
    for c in cases:
        by_stage[c["current_stage"]] = by_stage.get(c["current_stage"], 0) + 1

    tasks = (
        ctx.actor.db.table("case_tasks")
        .select("status, sla_breached, due_date")
        .in_("case_id", case_ids)
        .execute()
        .data
    )
    today = date.today()
    overdue = sum(
        1
        for t in tasks
        if t["status"] in OPEN and t["due_date"] and date.fromisoformat(t["due_date"]) < today
    )

    documents = (
        ctx.actor.db.table("documents")
        .select("status")
        .in_("case_id", case_ids)
        .execute()
        .data
    )
    pending_docs = sum(1 for d in documents if d["status"] == "pending")

    return dump(
        {
            "open_cases": len(cases),
            "by_stage": by_stage,
            "tasks_overdue": overdue,
            "documents_pending": pending_docs,
            "note": "Reflects only what your own access returns — RLS already scoped this.",
        }
    )


def get_employee_profile(ctx: ToolContext, employee_id: str | None = None) -> str:
    eid = employee_id or ctx.actor.employee_id
    rows = (
        ctx.actor.db.table("employees")
        .select("id, full_name, emp_code, department, designation, date_of_joining, app_role, manager_id, is_active")
        .eq("id", eid)
        .limit(1)
        .execute()
    )
    if not rows.data:
        return f"No employee visible for id={eid} — it may not exist, or your access doesn't include it."
    return dump(rows.data[0])


def analyse_exit_interviews(ctx: ToolContext, limit: int = 40) -> str:
    """Every submitted exit interview the caller may read, for trend analysis.

    The per-case `summarize_exit_interview` tool answers "what did this person
    say". Nothing answered "what are people saying", which left the trend
    analyst with only `get_dashboard_metrics` — case counts, containing no
    interview content at all. It could not do its job.

    Returns the pre-computed sentiment and themes for counting, plus the raw
    answers so the model can find a pattern nobody tagged. Responses are the
    exiting employee's own words about their manager and the company, so they
    are wrapped as untrusted content (rule 3): the model reads them as data,
    never as instructions.

    Scope is RLS's. HR sees everything; a manager would see only their reports'
    cases, which is why the count of interviews used is returned — a theme
    drawn from two responses must not read as a company-wide finding.
    """
    interviews = (
        ctx.actor.db.table("exit_interviews")
        .select("case_id, responses, sentiment, themes, summary, submitted_at")
        .not_.is_("submitted_at", "null")
        .order("submitted_at", desc=True)
        .limit(min(limit, 100))
        .execute()
    ).data
    if not interviews:
        return (
            "No exit interviews have been submitted yet, so there is nothing to "
            "analyse. Say so plainly rather than describing what the themes "
            "might be."
        )

    # Department is the one attribute worth attaching: "three of four leavers in
    # DevOps" is actionable where a bare count is not. Names are left out — the
    # Exit Interview Policy promises themes, not attributed answers.
    cases = (
        ctx.actor.db.table("exit_cases")
        .select("id, employee:employees!exit_cases_employee_id_fkey(department)")
        .in_("id", [i["case_id"] for i in interviews])
        .execute()
    ).data
    department_for = {c["id"]: (c["employee"] or {}).get("department") for c in cases}

    sentiments: dict[str, int] = {}
    theme_counts: dict[str, int] = {}
    for row in interviews:
        sentiments[row["sentiment"] or "unrated"] = (
            sentiments.get(row["sentiment"] or "unrated", 0) + 1
        )
        for theme in row.get("themes") or []:
            theme_counts[theme] = theme_counts.get(theme, 0) + 1

    body = {
        "interviews_analysed": len(interviews),
        "sentiment_counts": sentiments,
        "theme_counts": dict(
            sorted(theme_counts.items(), key=lambda kv: -kv[1])
        ),
        "responses": [
            {
                "department": department_for.get(row["case_id"]),
                "sentiment": row["sentiment"],
                "themes": row.get("themes") or [],
                "answers": row.get("responses") or {},
            }
            for row in interviews
        ],
    }

    return (
        f"{len(interviews)} submitted exit interview(s). Counts are already "
        f"tallied; the answers below are the employees' own words.\n"
        + wrap_untrusted(dump(body))
    )


TOOLS = [
    ToolSpec(
        name="get_exit_case",
        description="Read one exit case (defaults to the case in context) — stage, status, risk score, and its checklist tasks.",
        input_schema={
            "type": "object",
            "properties": {"case_id": {"type": "string", "description": "Defaults to the case already in context."}},
        },
        fn=get_exit_case,
    ),
    ToolSpec(
        name="analyse_exit_interviews",
        description=(
            "Every submitted exit interview you may read, with sentiment and "
            "theme counts already tallied plus the raw answers. Use for "
            "questions about patterns across leavers — why people leave, what "
            "they valued, what they want changed. For one person's interview "
            "use summarize_exit_interview instead."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "How many recent interviews to read. Default 40.",
                }
            },
        },
        fn=analyse_exit_interviews,
    ),
    ToolSpec(
        name="list_cases",
        description="List exit cases visible to you. scope='mine' is your own case, 'team' is your direct reports, 'all' is everything RLS returns.",
        input_schema={
            "type": "object",
            "properties": {"scope": {"type": "string", "enum": ["mine", "team", "all"]}},
        },
        fn=list_cases,
    ),
    ToolSpec(
        name="get_checklist",
        description="Read the full task checklist for a case (defaults to the case in context).",
        input_schema={
            "type": "object",
            "properties": {"case_id": {"type": "string", "description": "Defaults to the case already in context."}},
        },
        fn=get_checklist,
    ),
    ToolSpec(
        name="search_policy_docs",
        description="Text search over indexed policy document chunks. Returns nothing if the topic isn't covered — say so, don't guess.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        fn=search_policy_docs,
    ),
    ToolSpec(
        name="get_dashboard_metrics",
        description="Aggregate counts across every case your access returns: open cases by stage, overdue tasks, pending documents.",
        input_schema={"type": "object", "properties": {}},
        fn=get_dashboard_metrics,
    ),
    ToolSpec(
        name="get_employee_profile",
        description="Read one employee's profile (defaults to yourself) — department, designation, tenure, role, manager.",
        input_schema={
            "type": "object",
            "properties": {"employee_id": {"type": "string", "description": "Defaults to the calling employee."}},
        },
        fn=get_employee_profile,
    ),
]
