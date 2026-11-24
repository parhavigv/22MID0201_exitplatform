"""Pydantic output shapes for the analysis tools that use `call_structured()`
(`client.beta.messages.parse()`) instead of free-text tool replies — these are
the results that get written into `agent_actions.payload` as a draft, and
later (Phase 4's executor) into the real columns named in each docstring
below, once a human approves.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DocumentVerification(BaseModel):
    """Written to `documents.verification` (migration 0008) at upload time.

    Advisory only. A `belongs=False` verdict warns the employee and flags the
    document for its reviewer; it never rejects the upload, because the model
    will sometimes be wrong and an employee must not be locked out of their own
    offboarding by a misread file.
    """

    belongs: bool
    """True when the file is the document type that was asked for."""

    detected_type: str = Field(
        description="What the document actually appears to be, in a few words. "
        "Echo the expected type back when it matches."
    )
    reason: str = Field(
        description="One plain sentence a non-technical reader understands. "
        "Shown to both the employee and their manager."
    )
    confidence: Literal["high", "medium", "low"]


class RiskAssessment(BaseModel):
    """Drafted into `exit_cases.risk_score` on approval."""

    risk_score: int = Field(ge=0, le=100)
    risk_level: Literal["low", "medium", "high"]
    reasons: list[str] = Field(default_factory=list)


class ComplianceResult(BaseModel):
    """Not a database column today — surfaces in the draft for HR to act on,
    or feeds `flag_policy_breach` when a gap needs its own action."""

    compliant: bool
    gaps: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class InterviewSummary(BaseModel):
    """Drafted into `exit_interviews.sentiment/themes/summary/recommendations`
    on approval."""

    sentiment: Literal["positive", "neutral", "negative", "mixed"]
    themes: list[str] = Field(default_factory=list)
    summary: str
    recommendations: list[str] = Field(default_factory=list)


class KtReviewResult(BaseModel):
    """Drafted into `kt_items.coverage_status`/`gap_note` on approval."""

    coverage_status: Literal["not_started", "in_progress", "documented", "verified", "gap"]
    gap_note: str | None = None
