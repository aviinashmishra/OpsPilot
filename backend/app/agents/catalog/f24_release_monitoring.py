"""Agent 24 - Release Monitoring.

Compares post-deployment telemetry (error rate, latency, saturation) with the
configured thresholds and the pre-deploy baseline, summarises possible causes
from logs, and opens incident alerts with recommended mitigations. It never
deploys, rolls back or changes infrastructure; a rollback is only ever a
recommendation attached to an approval-gated alert.
"""

from __future__ import annotations

import statistics
from typing import Any

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
from app.agents.common import parse_dt
from app.agents.registry import register
from app.agents.services import AgentServices

DEFAULT_THRESHOLDS = {"error_rate": 0.02, "p95_latency_ms": 800, "cpu": 0.85}


class ReleaseIn(AgentInput):
    service: str
    deployment_id: str | None = None
    window_minutes: int = Field(default=60, ge=10, le=1440)


class Observation(BaseModel):
    metric: str
    current: float
    baseline: float | None
    threshold: float | None
    breached: bool
    change_pct: float | None


class ReleaseOut(BaseModel):
    service: str
    deployment: dict[str, Any] | None
    observations: list[Observation]
    anomaly_detected: bool
    severity: str
    possible_causes: list[str]
    recommended_mitigations: list[str]
    error_samples: list[dict[str, Any]]
    incident_title: str | None
    summary: str
    actions_taken: str


@register
class ReleaseMonitoringAgent(BaseAgent):
    spec = AgentSpec(
        key="release_monitoring",
        name="Release Monitoring Agent",
        department="technology_product",
        version="1.0.3",
        description="Watches post-release telemetry against thresholds and baselines, summarises likely causes from logs and raises incident alerts with mitigations; never touches infrastructure.",
        use_cases=["Post-deploy canary review", "Error-rate alerting", "Incident drafting"],
        input_model=ReleaseIn,
        output_model=ReleaseOut,
        allowed_tools=["monitoring.get_deployments", "monitoring.get_metrics", "monitoring.get_logs", "monitoring.create_alert", "chat.post_message"],
        permission_scopes=["monitoring:read", "monitoring:write", "chat:write"],
        policies=["thresholds_from_config", "no_infra_changes", "rollback_is_recommendation_only"],
        approval_rules=[ApprovalRule(action_type="release.rollback_recommendation", condition="rollback recommendations are reviewed by on-call")],
        timeout_seconds=60,
        token_budget=6000,
        risk_level="medium",
        baseline_minutes_saved=20,
    )

    def run(self, ctx: AgentContext, payload: ReleaseIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        deploys = services.tools.call("monitoring.get_deployments", service=payload.service, limit=5).get("items", [])
        deploy = next((d for d in deploys if d.get("id") == payload.deployment_id), deploys[0] if deploys else None)
        if deploy:
            result.add_evidence(f"monitoring:deployment:{deploy['id']}", excerpt=f"{deploy.get('version')} at {deploy.get('deployed_at')}", source_type="monitoring")
        metrics = services.tools.call("monitoring.get_metrics", service=payload.service, window_minutes=payload.window_minutes * 2)
        if not metrics.get("found"):
            result.status = "needs_input"
            result.missing_information = [f"No telemetry for service '{payload.service}'"]
            result.data = ReleaseOut(service=payload.service, deployment=deploy, observations=[], anomaly_detected=False, severity="none", possible_causes=[], recommended_mitigations=[], error_samples=[], incident_title=None, summary="No telemetry available", actions_taken="none").model_dump()
            result.summary = "No telemetry available"
            return result
        thresholds = {**DEFAULT_THRESHOLDS, **(metrics.get("thresholds") or {}), **(ctx.agent_config.get("thresholds") or {})}
        points = metrics["points"]
        deployed_at = parse_dt(deploy.get("deployed_at")) if deploy else None
        if deployed_at:
            before = [p for p in points if (parse_dt(p.get("ts")) or ctx.now) < deployed_at]
            after = [p for p in points if (parse_dt(p.get("ts")) or ctx.now) >= deployed_at] or points[-payload.window_minutes:]
        else:
            half = len(points) // 2
            before, after = points[:half], points[half:]
        observations: list[Observation] = []
        for m in ("error_rate", "p95_latency_ms", "cpu"):
            cur_vals = [float(p[m]) for p in after if p.get(m) is not None]
            base_vals = [float(p[m]) for p in before if p.get(m) is not None]
            if not cur_vals:
                continue
            cur = statistics.fmean(cur_vals)
            base = statistics.fmean(base_vals) if base_vals else None
            thr = thresholds.get(m)
            change = round((cur - base) / base * 100, 1) if base else None
            breached = (thr is not None and cur > thr) or (base is not None and change is not None and change >= 100 and cur > (thr or 0) * 0.5)
            observations.append(Observation(metric=m, current=round(cur, 4), baseline=round(base, 4) if base is not None else None, threshold=thr, breached=bool(breached), change_pct=change))
            result.add_evidence(f"metric:{payload.service}:{m}", excerpt=f"now {cur:.4f} vs baseline {base if base is not None else 'n/a'} (threshold {thr})", source_type="monitoring")
        breached = [o for o in observations if o.breached]
        anomaly = bool(breached)
        severity = "none" if not anomaly else ("critical" if any(o.metric == "error_rate" and o.current >= 2 * (o.threshold or 0.02) for o in breached) else "high" if any(o.metric == "error_rate" for o in breached) else "medium")
        logs = services.tools.call("monitoring.get_logs", service=payload.service, level="error", limit=30).get("items", []) if anomaly else []
        samples = [{"ts": e.get("ts"), "message": str(e.get("message"))[:200], "count": e.get("count", 1)} for e in logs[:5]]
        for e in logs[:5]:
            result.add_evidence(f"log:{payload.service}:{e.get('id', e.get('ts'))}", excerpt=str(e.get("message"))[:160], source_type="monitoring")
        causes: list[str] = []
        if anomaly:
            if deploy:
                causes.append(f"Regression introduced by deployment {deploy.get('id')} ({deploy.get('version')}) — anomaly began after deploy time")
            from collections import Counter

            top = Counter(str(e.get("message", ""))[:60] for e in logs).most_common(3)
            for msg, n in top:
                causes.append(f"Recurring error ({n}×): {msg}")
            if any(o.metric == "cpu" for o in breached):
                causes.append("CPU saturation — possible inefficient code path or traffic increase")
            if any(o.metric == "p95_latency_ms" for o in breached) and not any(o.metric == "error_rate" for o in breached):
                causes.append("Latency regression without errors — likely downstream dependency or query plan change")
        mitigations = []
        if anomaly:
            mitigations.append(f"Recommend rollback of {deploy.get('id') if deploy else 'the latest release'} (requires on-call approval; this agent does not deploy)" if deploy and severity in {"critical", "high"} else "Monitor for 15 more minutes and compare against baseline")
            mitigations += ["Page the service owner", "Capture a diagnostic bundle (logs, traces, recent config changes)", "Scale out if saturation persists (infrastructure change requires authorisation)"]
        title = f"[{severity.upper()}] {payload.service}: " + ", ".join(f"{o.metric} {o.current:.3g} > {o.threshold}" for o in breached if o.threshold is not None) if anomaly else None
        summary = ("Anomaly after release: " + "; ".join(f"{o.metric} {o.current:.4g} (baseline {o.baseline}, threshold {o.threshold}, {o.change_pct:+.0f}%)" if o.change_pct is not None else f"{o.metric} {o.current:.4g} (threshold {o.threshold})" for o in breached)) if anomaly else f"{payload.service} within thresholds after release ({len(observations)} metric(s) checked)"
        if anomaly:
            result.proposed_actions.append(ProposedAction(action_type="monitoring.create_alert", tool_key="monitoring.create_alert", payload={"title": title, "severity": severity, "body": summary + "\n\nPossible causes:\n- " + "\n- ".join(causes) + "\n\nMitigations:\n- " + "\n- ".join(mitigations), "service": payload.service}, reason="Open incident alert", risk_level="medium", evidence_refs=result.evidence_refs[:6], estimated_minutes_saved=15))
            result.proposed_actions.append(ProposedAction(action_type="chat.notify", tool_key="chat.post_message", payload={"channel": ctx.agent_config.get("oncall_channel", "#incidents"), "text": f"{title}\n{summary}"}, reason="Notify on-call", risk_level="low", evidence_refs=result.evidence_refs[:3]))
            if deploy and severity in {"critical", "high"}:
                result.proposed_actions.append(ProposedAction(action_type="release.rollback_recommendation", tool_key="monitoring.create_alert", payload={"title": f"Rollback recommendation: {payload.service} {deploy.get('version')}", "severity": severity, "body": f"Recommend rolling back deployment {deploy.get('id')}. Evidence: {summary}. The agent cannot execute rollbacks; an authorised engineer must perform it.", "service": payload.service}, reason="Rollback recommendation for on-call decision", risk_level="high", requires_approval=True, evidence_refs=result.evidence_refs[:4]))
            result.status = "escalated"
        result.data = ReleaseOut(service=payload.service, deployment=deploy, observations=observations, anomaly_detected=anomaly, severity=severity, possible_causes=causes, recommended_mitigations=mitigations, error_samples=samples, incident_title=title, summary=summary, actions_taken="alert + notification proposed; no infrastructure changes" if anomaly else "none").model_dump()
        result.summary = summary
        result.confidence = 0.85
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved
        return result
