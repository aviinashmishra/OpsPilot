"""Agent 22 - Bug Triage.

Normalises bug reports, finds likely duplicates with text similarity against
verified tracker issues, suggests severity/priority from documented rules,
drafts reproduction steps and lists required diagnostics. Uncertain or
high-impact classifications require human review before the issue is filed.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.base import (
    AgentContext,
    AgentInput,
    AgentResult,
    AgentSpec,
    ApprovalRule,
    BaseAgent,
    ProposedAction,
)
from app.agents.common import guard_untrusted, sentences
from app.agents.registry import register
from app.agents.services import AgentServices

SEVERITY_RULES: list[tuple[str, list[str]]] = [
    ("critical", ["data loss", "security", "breach", "outage", "down for all", "cannot log in", "payment fails", "crash on launch", "all users"]),
    ("high", ["crash", "500", "error for many", "blocked", "cannot complete", "wrong amount", "duplicate charge", "regression"]),
    ("medium", ["incorrect", "wrong", "slow", "timeout", "sometimes", "intermittent", "broken link", "not updating"]),
    ("low", ["typo", "alignment", "cosmetic", "color", "colour", "spacing", "minor"]),
]
DIAGNOSTICS = {"frontend": ["Browser and version", "Console errors", "HAR file / network trace", "Screenshot or recording"], "backend": ["Request ID / correlation ID", "Timestamp (UTC)", "Server logs around the time", "Environment (staging/prod)"], "mobile": ["Device model and OS version", "App version", "Crash log", "Steps and frequency"], "data": ["Affected record IDs", "Expected vs actual values", "Data source and refresh time"]}


class BugReport(BaseModel):
    title: str = Field(max_length=200)
    description: str = Field(min_length=5, max_length=20_000)
    reporter: str | None = None
    component: str | None = None
    environment: str | None = None
    version: str | None = None
    affected_users: int | None = None


class BugIn(AgentInput):
    report: BugReport
    project: str = "ENG"
    duplicate_threshold: float = Field(default=0.72, ge=0.3, le=1.0)


class Normalized(BaseModel):
    summary: str = Field(max_length=200)
    expected: str | None = None
    actual: str | None = None
    repro_steps: list[str] = Field(default_factory=list)
    component_guess: str | None = None


class BugOut(BaseModel):
    normalized: Normalized
    severity: str
    priority: str
    severity_rule: str
    confidence: float
    likely_duplicates: list[dict[str, Any]]
    is_probable_duplicate: bool
    required_diagnostics: list[str]
    needs_human_review: bool
    review_reason: str | None
    issue_proposed: bool


def normalize_heuristic(r: BugReport) -> Normalized:
    text = r.description
    exp = act = None
    m = re.search(r"expected[:\s]+(.+?)(?:\.|\n|$)", text, re.I)
    if m:
        exp = m.group(1).strip()[:300]
    m = re.search(r"(?:actual|instead|but)[:\s]+(.+?)(?:\.|\n|$)", text, re.I)
    if m:
        act = m.group(1).strip()[:300]
    steps = [re.sub(r"^\s*(\d+[.)]|-|\*)\s*", "", ln).strip() for ln in text.splitlines() if re.match(r"^\s*(\d+[.)]|-|\*)\s+", ln)]
    comp = r.component
    if not comp:
        low = text.lower()
        comp = "frontend" if any(w in low for w in ("button", "page", "screen", "ui", "browser", "click")) else "mobile" if any(w in low for w in ("ios", "android", "app crashes")) else "data" if any(w in low for w in ("report", "export", "numbers", "dashboard")) else "backend"
    return Normalized(summary=r.title[:200], expected=exp, actual=act, repro_steps=steps[:12] or [s[:160] for s in sentences(text)[:4]], component_guess=comp)


def similarity(a: str, b: str) -> float:
    from rapidfuzz import fuzz

    return max(fuzz.token_set_ratio(a, b), fuzz.partial_ratio(a[:200], b[:200])) / 100


@register
class BugTriageAgent(BaseAgent):
    spec = AgentSpec(
        key="bug_triage",
        name="Bug Triage Agent",
        department="technology_product",
        version="1.1.0",
        description="Normalises bug reports, detects duplicates via similarity against verified issues, applies documented severity rules and drafts reproduction/diagnostic requests, deferring uncertain cases to humans.",
        use_cases=["Inbound bug intake", "Duplicate detection", "Severity suggestions"],
        input_model=BugIn,
        output_model=BugOut,
        allowed_tools=["issues.search", "issues.get", "issues.create", "issues.comment"],
        permission_scopes=["issues:read", "issues:write"],
        policies=["documented_severity_rules", "verified_duplicates_only", "human_review_when_uncertain"],
        approval_rules=[ApprovalRule(action_type="issues.create", condition="critical severity or probable duplicate")],
        timeout_seconds=60,
        token_budget=6000,
        risk_level="low",
        model_tier="fast",
        baseline_minutes_saved=10,
    )

    def run(self, ctx: AgentContext, payload: BugIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        r = payload.report
        wrapped = guard_untrusted(result, f"{r.title}\n{r.description}", "bug_report")
        norm = services.structured(task="bug_normalize", schema=Normalized, system="Normalise a bug report: one-line summary, expected vs actual behaviour (only if stated), reproduction steps as stated, and a component guess (frontend/backend/mobile/data).", user=wrapped, heuristic=lambda: normalize_heuristic(r), tier="fast")
        result.add_evidence("input:bug_report", excerpt=r.title, source_type="input")
        text = f"{r.title} {r.description}".lower()
        severity, rule = "medium", "default (no rule matched)"
        for sev, words in SEVERITY_RULES:
            hit = [w for w in words if w in text]
            if hit:
                severity, rule = sev, f"keyword rule '{hit[0]}' → {sev}"
                break
        if r.affected_users and r.affected_users >= int(ctx.agent_config.get("critical_user_threshold", 1000)) and severity != "critical":
            severity, rule = "critical", f"{r.affected_users} affected users ≥ threshold"
        priority = {"critical": "P0", "high": "P1", "medium": "P2", "low": "P3"}[severity]
        conf = 0.9 if "keyword" in rule or "threshold" in rule else 0.5

        candidates = services.tools.call("issues.search", query=" ".join(re.findall(r"[a-z]{4,}", r.title.lower())[:4]), project=payload.project, limit=50).get("items", [])
        if len(candidates) < 5:
            candidates += [c for c in services.tools.call("issues.search", project=payload.project, limit=100).get("items", []) if c not in candidates]
        dups = []
        for c in candidates:
            if c.get("status") in {"closed", "done", "wontfix"}:
                continue
            s = similarity(f"{r.title} {norm.summary}", f"{c.get('title', '')} {c.get('description', '')[:300]}")
            if s >= payload.duplicate_threshold:
                dups.append({"key": c["id"], "title": c.get("title"), "status": c.get("status"), "similarity": round(s, 3)})
                result.add_evidence(f"issues:{c['id']}", excerpt=c.get("title"), source_type="issue_tracker")
        dups.sort(key=lambda d: -d["similarity"])
        probable = bool(dups and dups[0]["similarity"] >= max(payload.duplicate_threshold, 0.85))
        diagnostics = DIAGNOSTICS.get(norm.component_guess or "backend", DIAGNOSTICS["backend"])
        missing = []
        if not norm.repro_steps:
            missing.append("Reproduction steps")
        if not norm.expected:
            missing.append("Expected behaviour")
        if not r.environment:
            missing.append("Environment")
        result.missing_information = missing
        review, reason = False, None
        if severity == "critical":
            review, reason = True, "Critical severity requires human confirmation"
        elif probable:
            review, reason = True, f"Probable duplicate of {dups[0]['key']} ({dups[0]['similarity']:.0%})"
        elif conf < 0.6:
            review, reason = True, "Severity could not be determined from documented rules"
        desc = f"{norm.summary}\n\nExpected: {norm.expected or 'not stated'}\nActual: {norm.actual or 'not stated'}\n\nSteps:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(norm.repro_steps, 1)) + f"\n\nEnvironment: {r.environment or '?'} · Version: {r.version or '?'} · Reporter: {r.reporter or '?'}\nSeverity rule: {rule}\nDiagnostics needed: {', '.join(diagnostics)}" + (f"\nPossible duplicates: {', '.join(d['key'] for d in dups[:3])}" if dups else "")
        if probable:
            result.proposed_actions.append(ProposedAction(action_type="issues.comment", tool_key="issues.comment", payload={"issue_key": dups[0]["key"], "body": f"Possible duplicate report received: '{r.title}' (similarity {dups[0]['similarity']:.0%}).\n\n{desc[:1500]}"}, reason="Link duplicate report to the existing issue", risk_level="low", evidence_refs=[f"issues:{dups[0]['key']}"], estimated_minutes_saved=5))
        result.proposed_actions.append(ProposedAction(action_type="issues.create", tool_key="issues.create", payload={"project": payload.project, "title": norm.summary, "description": desc, "priority": severity, "issue_type": "bug", "labels": ["triage", norm.component_guess or "unknown"] + (["possible-duplicate"] if dups else [])}, reason=f"File bug ({severity}/{priority})" + (f" — {reason}" if review else ""), risk_level="medium" if review else "low", requires_approval=review, evidence_refs=["input:bug_report"], estimated_minutes_saved=8))
        result.data = BugOut(normalized=norm, severity=severity, priority=priority, severity_rule=rule, confidence=conf, likely_duplicates=dups[:5], is_probable_duplicate=probable, required_diagnostics=diagnostics, needs_human_review=review, review_reason=reason, issue_proposed=True).model_dump()
        result.summary = f"{severity}/{priority} ({rule}); {len(dups)} possible duplicate(s)" + (f"; review: {reason}" if review else "")
        result.confidence = conf
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved
        return result


Literal  # noqa: B018
