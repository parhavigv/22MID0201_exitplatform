"""The worker registry — 19 personas (row 16 from the user's list is the
supervisor itself; see `prompts.py` and the plan for why). A worker is a
data row here, not a graph node — `graph.py`'s `worker_node` is one function
that looks a key up in `WORKER_REGISTRY` and calls the model with that row's
prompt and tool subset. Adding a 20th persona later means adding a row here
and a prompt in `prompts.py`, not a new node.

`kind` is descriptive only (used by the dashboard and for readability in this
file) — every worker is driven the same way, through ordinary tool-calling.
The four "structured" workers do their DB-writable parsing *inside* their one
tool (`tools/drafts.py`, via `call_structured`), not at this level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.agent import prompts


@dataclass(frozen=True)
class WorkerSpec:
    name: str
    prompt: str
    tools: tuple[str, ...]
    kind: Literal["chat", "draft", "structured", "sweep"]
    dashboard_visible: bool = True


WORKER_REGISTRY: dict[str, WorkerSpec] = {
    "checklist_generator": WorkerSpec(
        name="Exit Checklist Generator",
        prompt=prompts.CHECKLIST_GENERATOR_PROMPT,
        tools=("get_exit_case", "get_checklist", "generate_exit_checklist"),
        kind="draft",
    ),
    "email_drafting": WorkerSpec(
        name="Email Drafting",
        prompt=prompts.EMAIL_DRAFTING_PROMPT,
        tools=("get_exit_case", "get_employee_profile", "draft_notification"),
        kind="draft",
    ),
    "faq_chatbot": WorkerSpec(
        name="FAQ Chatbot",
        prompt=prompts.FAQ_CHATBOT_PROMPT,
        tools=("search_policy_docs", "get_exit_case", "get_checklist", "list_cases"),
        kind="chat",
    ),
    "interview_summarizer": WorkerSpec(
        name="Exit Interview Summarizer",
        prompt=prompts.INTERVIEW_SUMMARIZER_PROMPT,
        tools=("summarize_exit_interview",),
        kind="structured",
    ),
    "sla_escalation": WorkerSpec(
        name="SLA Escalation",
        prompt=prompts.SLA_ESCALATION_PROMPT,
        tools=("list_cases", "draft_escalation"),
        kind="sweep",
        dashboard_visible=False,
    ),
    "kt_doc_reviewer": WorkerSpec(
        name="KT Document Reviewer",
        prompt=prompts.KT_DOC_REVIEWER_PROMPT,
        tools=("review_kt_document",),
        kind="structured",
    ),
    "smart_routing": WorkerSpec(
        name="Smart Routing",
        prompt=prompts.SMART_ROUTING_PROMPT,
        tools=("get_exit_case", "list_cases"),
        kind="draft",
    ),
    "risk_assessment": WorkerSpec(
        name="Exit Risk Assessment",
        prompt=prompts.RISK_ASSESSMENT_PROMPT,
        tools=("assess_exit_risk",),
        kind="structured",
    ),
    "compliance_verification": WorkerSpec(
        name="Compliance Verification",
        prompt=prompts.COMPLIANCE_VERIFICATION_PROMPT,
        tools=("verify_compliance", "search_policy_docs"),
        kind="structured",
    ),
    "dashboard_insights": WorkerSpec(
        name="Dashboard Insights",
        prompt=prompts.DASHBOARD_INSIGHTS_PROMPT,
        # Aggregate counts answer "how many"; the case list answers "which
        # ones", which is the follow-up question every time.
        tools=("get_dashboard_metrics", "list_cases"),
        kind="chat",
    ),
    "multi_system_clearance": WorkerSpec(
        name="Multi-System Clearance",
        prompt=prompts.MULTI_SYSTEM_CLEARANCE_PROMPT,
        # One read tool meant it could confirm a case existed and nothing else.
        # The employee profile carries the actual systems held and the role on
        # each, which is the whole substance of a clearance summary.
        tools=(
            "get_exit_case",
            "get_employee_profile",
            "get_checklist",
            "draft_notification",
        ),
        kind="draft",
    ),
    "document_collection": WorkerSpec(
        name="Document Collection",
        prompt=prompts.DOCUMENT_COLLECTION_PROMPT,
        tools=("get_checklist", "request_document"),
        kind="draft",
    ),
    "workflow_optimizer": WorkerSpec(
        name="Exit Workflow Optimizer",
        prompt=prompts.WORKFLOW_OPTIMIZER_PROMPT,
        tools=("get_dashboard_metrics", "list_cases"),
        kind="chat",
    ),
    "it_deprovisioning": WorkerSpec(
        name="IT Deprovisioning Planner",
        prompt=prompts.IT_DEPROVISIONING_PROMPT,
        # Role and department are what make the plan specific rather than
        # generic, and the checklist stops it proposing work already recorded.
        # draft_notification is what actually records the plan. Without a draft
        # tool this worker could only read and talk — and it duly announced
        # "queued as a pending draft" with nothing behind it. A worker whose
        # prompt promises a draft must hold a tool that makes one.
        tools=(
            "get_exit_case",
            "get_employee_profile",
            "get_checklist",
            "draft_notification",
            "update_task_status",
        ),
        kind="draft",
    ),
    "settlement_drafter": WorkerSpec(
        name="Settlement Drafter",
        prompt=prompts.SETTLEMENT_DRAFTER_PROMPT,
        # search_policy_docs is the important one: the F&F components and the
        # notice-shortfall rule are written down, so the draft cites them
        # instead of the model recalling how settlements usually work.
        tools=(
            "get_exit_case",
            "get_employee_profile",
            "get_checklist",
            "search_policy_docs",
            "draft_notification",
        ),
        kind="draft",
    ),
    "access_risk_watcher": WorkerSpec(
        name="Access Risk Watcher",
        prompt=prompts.ACCESS_RISK_WATCHER_PROMPT,
        tools=("list_cases", "get_dashboard_metrics", "draft_escalation"),
        kind="sweep",
        # Nightly, not conversational — its output belongs in the approval
        # queue, not in a chat window.
        dashboard_visible=False,
    ),
    "interview_trend_analyst": WorkerSpec(
        name="Exit Interview Trend Analyst",
        prompt=prompts.INTERVIEW_TREND_ANALYST_PROMPT,
        # It had only get_dashboard_metrics, which holds case counts and no
        # interview content whatever — so it was asked about themes and had
        # nothing to read. Hidden from the dashboard for the same reason.
        tools=("analyse_exit_interviews", "get_dashboard_metrics"),
        kind="chat",
        dashboard_visible=True,
    ),
    "rehire_assessment": WorkerSpec(
        name="Intelligent Rehire Assessment",
        prompt=prompts.REHIRE_ASSESSMENT_PROMPT,
        # Whether someone would be welcome back turns largely on how they left
        # and what they said on the way out — neither of which the profile
        # alone shows.
        tools=("get_employee_profile", "get_exit_case", "analyse_exit_interviews"),
        kind="structured",
    ),
    "policy_compliance_auditor": WorkerSpec(
        name="Policy Compliance Auditor",
        prompt=prompts.POLICY_COMPLIANCE_AUDITOR_PROMPT,
        tools=("list_cases", "verify_compliance", "flag_policy_breach"),
        kind="sweep",
        dashboard_visible=False,
    ),
    "predictive_attrition": WorkerSpec(
        name="Predictive Attrition",
        prompt=prompts.PREDICTIVE_ATTRITION_PROMPT,
        # Case counts alone cannot suggest where attrition is building. Why
        # people actually left, by department, is the nearest honest signal
        # this platform holds.
        tools=("get_dashboard_metrics", "list_cases", "analyse_exit_interviews"),
        kind="sweep",
        dashboard_visible=False,
    ),
    "end_to_end_automation": WorkerSpec(
        name="End-to-End Exit Automation",
        prompt=prompts.END_TO_END_AUTOMATION_PROMPT,
        tools=(
            "get_exit_case",
            "get_checklist",
            "verify_compliance",
            "request_document",
            "draft_escalation",
        ),
        kind="sweep",
        dashboard_visible=False,
    ),
}
