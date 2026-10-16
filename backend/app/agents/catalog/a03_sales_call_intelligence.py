"""Agent 3 - Sales Call Intelligence.

Processes authorised call transcripts and extracts requirements, objections,
decisions, buying signals and next steps - every item linked to the transcript
line(s) that support it. Sentiment/intent are only reported when explicitly
stated by a speaker.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentResult, AgentSpec, BaseAgent, ProposedAction
from app.agents.common import guard_untrusted, number_lines
from app.agents.registry import register
from app.agents.services import AgentServices

Category = Literal["requirement", "objection", "decision", "buying_signal", "next_step"]

PATTERNS: dict[str, list[str]] = {
    "requirement": [r"\bwe need\b", r"\bneed(s)? to\b", r"\bmust\b", r"\brequire", r"\blooking for\b", r"\bimportant (for|to) us\b", r"\bhas to\b", r"\bintegrat(e|ion) with\b"],
    "objection": [r"\bconcern", r"\btoo expensive\b", r"\bexpensive\b", r"\bworried\b", r"\bnot sure\b", r"\bhesita", r"\bproblem with\b", r"\bdeal[- ]?breaker\b", r"\bover budget\b", r"\bcompetitor\b"],
    "decision": [r"\bwe (have )?decided\b", r"\bagreed\b", r"\blet'?s go with\b", r"\bwe will go\b", r"\bwe('ve| have)? approved\b", r"\bsigned off\b"],
    "buying_signal": [r"\bbudget\b", r"\bpricing\b", r"\bcontract\b", r"\bhow soon\b", r"\bwhen can (we|you)\b", r"\bpilot\b", r"\btrial\b", r"\bprocurement\b", r"\blegal review\b", r"\bpurchase order\b", r"\broll ?out\b"],
    "next_step": [r"\bsend (over|you|us)\b", r"\bfollow[- ]up\b", r"\bschedule\b", r"\bset up a\b", r"\bnext (week|step|call)\b", r"\bI'?ll (send|share|loop|get)\b", r"\bwe'?ll (send|share|review)\b"],
}
EXPLICIT_SENTIMENT = {
    "positive": [r"\b(love|excited|impressed|great fit|really like)\b"],
    "negative": [r"\b(frustrated|disappointed|unhappy|not impressed|don'?t like)\b"],
}


class CallIn(AgentInput):
    transcript: str = Field(min_length=20, max_length=200_000)
    consent_confirmed: bool = Field(description="Recording/processing consent confirmed for all participants")
    lead_id: str | None = None
    call_title: str | None = None
    our_speakers: list[str] = Field(default_factory=list, description="Names of our own reps (to attribute customer statements correctly)")


class Finding(BaseModel):
    category: Category
    text: str
    speaker: str | None = None
    line_refs: list[int]
    quote: str


class ExtractionOut(BaseModel):
    findings: list[Finding] = Field(default_factory=list)


class CallOut(BaseModel):
    call_title: str | None = None
    requirements: list[Finding]
    objections: list[Finding]
    decisions: list[Finding]
    buying_signals: list[Finding]
    next_steps: list[Finding]
    explicit_sentiment: list[dict] = Field(default_factory=list)
    summary: str
    participants: list[str]
    line_count: int
    rejected_unsupported: int = 0


def heuristic_extract(lines: list[dict], our_speakers: set[str]) -> ExtractionOut:
    findings: list[Finding] = []
    for ln in lines:
        text = ln["text"]
        for cat, pats in PATTERNS.items():
            if cat in {"requirement", "objection", "buying_signal"} and ln["speaker"] and ln["speaker"].lower() in our_speakers:
                continue  # statements by our own reps are not customer requirements/objections
            if any(re.search(p, text, re.I) for p in pats):
                findings.append(Finding(category=cat, text=text[:300], speaker=ln["speaker"], line_refs=[ln["line"]], quote=text[:200]))  # type: ignore[arg-type]
                break
    return ExtractionOut(findings=findings)


@register
class SalesCallIntelligenceAgent(BaseAgent):
    spec = AgentSpec(
        key="sales_call_intelligence",
        name="Sales Call Intelligence Agent",
        department="sales_revenue",
        version="1.0.3",
        description="Extracts requirements, objections, decisions, buying signals and next steps from authorised call transcripts, each linked to transcript evidence.",
        use_cases=["Post-call summaries", "Deal risk review", "CRM note automation"],
        input_model=CallIn,
        output_model=CallOut,
        allowed_tools=["crm.log_activity"],
        permission_scopes=["crm:write"],
        policies=["authorized_transcripts_only", "evidence_linked_claims", "no_inferred_sentiment"],
        timeout_seconds=120,
        token_budget=24000,
        risk_level="low",
        baseline_minutes_saved=20,
    )

    def run(self, ctx: AgentContext, payload: CallIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        if not payload.consent_confirmed:
            result.status = "needs_input"
            result.missing_information = ["Confirmation that all participants consented to recording and processing"]
            result.data = CallOut(call_title=payload.call_title, requirements=[], objections=[], decisions=[], buying_signals=[], next_steps=[], summary="Not processed: consent not confirmed", participants=[], line_count=0).model_dump()
            result.summary = "Transcript not processed - recording consent not confirmed"
            return result

        lines = number_lines(payload.transcript)
        by_line = {ln["line"]: ln for ln in lines}
        ours = {s.lower() for s in payload.our_speakers}
        wrapped = guard_untrusted(result, "\n".join(f"L{ln['line']} {ln['speaker'] or '?'}: {ln['text']}" for ln in lines), "call_transcript")
        extraction = services.structured(
            task="call_extraction",
            schema=ExtractionOut,
            system=(
                "Extract sales-call findings. Categories: requirement, objection, decision, buying_signal, next_step. "
                "Each finding must include the exact line numbers (from the L-prefix) and a verbatim quote from those lines. "
                "Do not infer emotions or intent that is not explicitly stated. Statements by our reps "
                f"({', '.join(payload.our_speakers) or 'unknown'}) are not customer requirements."
            ),
            user=wrapped,
            heuristic=lambda: heuristic_extract(lines, ours),
        )

        # Deterministic evidence validation: quotes must appear in the cited lines.
        valid: list[Finding] = []
        rejected = 0
        for f in extraction.findings:
            cited = " ".join(by_line[n]["text"] for n in f.line_refs if n in by_line)
            if not cited or _norm(f.quote)[:60] not in _norm(cited):
                rejected += 1
                continue
            valid.append(f)
        if rejected:
            result.warnings.append(f"Discarded {rejected} finding(s) whose quotes were not found in the cited transcript lines")
        for f in valid:
            result.add_evidence(f"transcript:line:{f.line_refs[0]}", excerpt=f.quote[:160], source_type="transcript")

        sentiment = []
        for ln in lines:
            for label, pats in EXPLICIT_SENTIMENT.items():
                if any(re.search(p, ln["text"], re.I) for p in pats):
                    sentiment.append({"label": label, "speaker": ln["speaker"], "line": ln["line"], "quote": ln["text"][:160], "basis": "explicit statement"})

        groups = {c: [f for f in valid if f.category == c] for c in ("requirement", "objection", "decision", "buying_signal", "next_step")}
        participants = sorted({ln["speaker"] for ln in lines if ln["speaker"]})
        summary = (
            f"{len(groups['requirement'])} requirement(s), {len(groups['objection'])} objection(s), {len(groups['decision'])} decision(s), "
            f"{len(groups['buying_signal'])} buying signal(s), {len(groups['next_step'])} next step(s) across {len(lines)} lines."
        )
        if not valid:
            result.warnings.append("No evidence-supported findings were extracted")
        result.data = CallOut(
            call_title=payload.call_title, requirements=groups["requirement"], objections=groups["objection"], decisions=groups["decision"],
            buying_signals=groups["buying_signal"], next_steps=groups["next_step"], explicit_sentiment=sentiment, summary=summary,
            participants=participants, line_count=len(lines), rejected_unsupported=rejected,
        ).model_dump()
        if payload.lead_id and valid:
            note = summary + "\nNext steps: " + "; ".join(f.text for f in groups["next_step"][:5])
            result.proposed_actions.append(ProposedAction(action_type="crm.log_activity", tool_key="crm.log_activity", payload={"lead_id": payload.lead_id, "activity_type": "call_summary", "note": note[:2000]}, reason="Attach evidence-linked call summary to the CRM record", risk_level="low", evidence_refs=result.evidence_refs[:5], estimated_minutes_saved=5))
        result.summary = summary
        result.confidence = 0.85 if valid else 0.4
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved
        return result


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()
