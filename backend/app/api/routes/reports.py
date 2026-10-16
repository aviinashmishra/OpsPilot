"""Overview, analytics, reports, usage, audit, incidents."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.agents.base import DEPARTMENT_LABELS
from app.agents.registry import agent_registry
from app.api.deps import Principal, require
from app.api.schemas import AuditEventOut, IncidentOut, OverviewOut, Page
from app.api.serializers import audit_out, incident_out, run_out
from app.core.errors import NotFound
from app.db.models import (
    AgentRun,
    Approval,
    AuditEvent,
    Incident,
    Integration,
    TenantAgentSetting,
    ToolExecution,
    WorkflowRun,
)
from app.db.session import get_db
from app.services.audit import verify_chain
from app.services.usage import period_totals, tenant_quotas

router = APIRouter(tags=["reports"])


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


def _roi_settings(principal: Principal) -> dict[str, float]:
    roi = (principal.tenant.settings or {}).get("roi", {}) or {}
    return {
        "loaded_hourly_cost_usd": float(roi.get("loaded_hourly_cost_usd", 45.0)),
        "infra_cost_per_run_usd": float(roi.get("infra_cost_per_run_usd", 0.002)),
        "realization_rate": float(roi.get("realization_rate", 0.0)),  # share of saved time converted into realized savings (verified by finance)
        "monthly_platform_fee_usd": float(roi.get("monthly_platform_fee_usd", 0.0)),
    }


@router.get("/reports/overview", response_model=OverviewOut, summary="Dashboard overview (persisted state only)")
def overview(days: int = Query(14, ge=1, le=90), principal: Principal = Depends(require("reports:read")), db: Session = Depends(get_db)) -> OverviewOut:
    tid = principal.tenant.id
    since = datetime.now(UTC) - timedelta(days=days)
    runs = db.execute(select(WorkflowRun).where(WorkflowRun.tenant_id == tid, WorkflowRun.created_at >= since)).scalars().all()
    disabled = {s.agent_key for s in db.execute(select(TenantAgentSetting).where(TenantAgentSetting.tenant_id == tid, TenantAgentSetting.enabled.is_(False))).scalars().all()}
    total_agents = len(agent_registry.all())
    active_agents = 0 if principal.tenant.emergency_disabled else total_agents - len(disabled)
    succeeded = [r for r in runs if r.status == "completed"]
    failed = [r for r in runs if r.status in {"failed", "timed_out"}]
    running = [r for r in runs if r.status in {"running", "pending", "waiting_approval"}]
    minutes = sum(r.estimated_minutes_saved for r in runs if r.status in {"completed", "waiting_approval"})
    ai_cost = sum(r.cost_usd for r in runs)
    roi = _roi_settings(principal)
    infra = round(len(runs) * roi["infra_cost_per_run_usd"], 4)
    pending = db.execute(select(func.count()).select_from(Approval).where(Approval.tenant_id == tid, Approval.status == "pending")).scalar_one()
    open_inc = db.execute(select(func.count()).select_from(Incident).where(Incident.tenant_id == tid, Incident.status == "open")).scalar_one()
    incidents = db.execute(select(Incident).where(Incident.tenant_id == tid).order_by(Incident.created_at.desc()).limit(6)).scalars().all()
    recent = db.execute(select(WorkflowRun).where(WorkflowRun.tenant_id == tid).order_by(WorkflowRun.created_at.desc()).limit(8)).scalars().all()

    series: dict[str, dict[str, Any]] = {}
    for i in range(days):
        d = (datetime.now(UTC) - timedelta(days=days - 1 - i)).date().isoformat()
        series[d] = {"date": d, "completed": 0, "failed": 0, "other": 0, "cost_usd": 0.0, "minutes_saved": 0.0}
    for r in runs:
        d = _aware(r.created_at).date().isoformat()  # type: ignore[union-attr]
        if d not in series:
            continue
        bucket = "completed" if r.status == "completed" else "failed" if r.status in {"failed", "timed_out"} else "other"
        series[d][bucket] += 1
        series[d]["cost_usd"] = round(series[d]["cost_usd"] + r.cost_usd, 6)
        if r.status in {"completed", "waiting_approval"}:
            series[d]["minutes_saved"] = round(series[d]["minutes_saved"] + r.estimated_minutes_saved, 2)

    agent_runs = db.execute(select(AgentRun.agent_key, AgentRun.status, func.count()).where(AgentRun.tenant_id == tid, AgentRun.created_at >= since).group_by(AgentRun.agent_key, AgentRun.status)).all()
    dept: dict[str, dict[str, Any]] = defaultdict(lambda: {"runs": 0, "succeeded": 0, "failed": 0})
    for key, status, n in agent_runs:
        if not agent_registry.has(key):
            continue
        d = agent_registry.get(key).spec.department
        dept[d]["runs"] += n
        if status in {"completed", "needs_approval"}:
            dept[d]["succeeded"] += n
        if status == "failed":
            dept[d]["failed"] += n
    modes: dict[str, int] = defaultdict(int)
    for integ in db.execute(select(Integration).where(Integration.tenant_id == tid)).scalars().all():
        modes["live_connected" if integ.mode == "live" and integ.status == "connected" else ("live_error" if integ.mode == "live" else "sandbox")] += 1

    return OverviewOut(
        active_agents=active_agents, total_agents=total_agents, workflows_executed=len(runs), workflows_succeeded=len(succeeded),
        workflows_failed=len(failed), workflows_running=len(running), estimated_minutes_saved=round(minutes, 1),
        realized_savings_usd=round(minutes / 60 * roi["loaded_hourly_cost_usd"] * roi["realization_rate"], 2),
        ai_cost_usd=round(ai_cost, 4), infra_cost_usd=infra, pending_approvals=pending, open_incidents=open_inc,
        recent_incidents=[incident_out(i) for i in incidents], recent_runs=[run_out(r) for r in recent], daily_series=list(series.values()),
        department_breakdown=[{"department": k, "label": DEPARTMENT_LABELS.get(k, k), **v} for k, v in sorted(dept.items())],
        integration_modes=dict(modes), period={"days": days, "since": since.isoformat()},
    )


@router.get("/reports", summary="Analytics report: KPIs, agent performance, ROI")
def reports(days: int = Query(30, ge=1, le=365), principal: Principal = Depends(require("reports:read")), db: Session = Depends(get_db)) -> dict[str, Any]:
    tid = principal.tenant.id
    since = datetime.now(UTC) - timedelta(days=days)
    runs = db.execute(select(WorkflowRun).where(WorkflowRun.tenant_id == tid, WorkflowRun.created_at >= since)).scalars().all()
    ars = db.execute(select(AgentRun).where(AgentRun.tenant_id == tid, AgentRun.created_at >= since)).scalars().all()
    tools = db.execute(select(ToolExecution).where(ToolExecution.tenant_id == tid, ToolExecution.created_at >= since)).scalars().all()
    approvals = db.execute(select(Approval).where(Approval.tenant_id == tid, Approval.created_at >= since)).scalars().all()
    roi = _roi_settings(principal)

    completed = [r for r in runs if r.status == "completed"]
    terminal = [r for r in runs if r.status in {"completed", "failed", "timed_out", "cancelled"}]
    latencies = sorted((_aware(r.finished_at) - _aware(r.started_at)).total_seconds() * 1000 for r in completed if r.started_at and r.finished_at)  # type: ignore[operator]
    total_cost = sum(r.cost_usd for r in runs)
    minutes = sum(r.estimated_minutes_saved for r in runs if r.status in {"completed", "waiting_approval"})
    side_effects = [t for t in tools if t.side_effect]
    dup_suppressed = sum(1 for t in side_effects if (t.response or {}).get("duplicate_suppressed"))
    decided = [a for a in approvals if a.decided_at]
    approval_latency = [(_aware(a.decided_at) - _aware(a.created_at)).total_seconds() / 60 for a in decided]  # type: ignore[operator]

    per_agent: dict[str, dict[str, Any]] = {}
    for a in ars:
        s = per_agent.setdefault(a.agent_key, {"agent_key": a.agent_key, "name": agent_registry.get(a.agent_key).spec.name if agent_registry.has(a.agent_key) else a.agent_key, "department": agent_registry.get(a.agent_key).spec.department if agent_registry.has(a.agent_key) else "", "runs": 0, "succeeded": 0, "failed": 0, "needs_approval": 0, "needs_input": 0, "cost_usd": 0.0, "tokens": 0, "latencies": [], "warnings": 0, "missing_info": 0})
        s["runs"] += 1
        s["cost_usd"] += a.cost_usd
        s["tokens"] += a.prompt_tokens + a.completion_tokens
        if a.latency_ms is not None:
            s["latencies"].append(a.latency_ms)
        s["warnings"] += len(a.warnings or [])
        s["missing_info"] += 1 if a.missing_information else 0
        if a.status in {"completed", "needs_approval"}:
            s["succeeded"] += 1
        if a.status == "needs_approval":
            s["needs_approval"] += 1
        if a.status == "needs_input":
            s["needs_input"] += 1
        if a.status == "failed":
            s["failed"] += 1
    agent_rows = []
    for s in per_agent.values():
        lat = sorted(s.pop("latencies"))
        agent_rows.append({**s, "cost_usd": round(s["cost_usd"], 6), "success_rate": round(s["succeeded"] / s["runs"], 4) if s["runs"] else None, "human_intervention_rate": round((s["needs_approval"] + s["needs_input"]) / s["runs"], 4) if s["runs"] else None, "p50_latency_ms": lat[len(lat) // 2] if lat else None, "p95_latency_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None, "cost_per_success_usd": round(s["cost_usd"] / s["succeeded"], 6) if s["succeeded"] else None})
    agent_rows.sort(key=lambda r: -r["runs"])

    labor_value = minutes / 60 * roi["loaded_hourly_cost_usd"]
    infra = len(runs) * roi["infra_cost_per_run_usd"]
    return {
        "period_days": days,
        "kpis": {
            "workflow_runs": len(runs),
            "workflow_completion_rate": round(len(completed) / len(terminal), 4) if terminal else None,
            "workflow_failure_rate": round(sum(1 for r in terminal if r.status in {"failed", "timed_out"}) / len(terminal), 4) if terminal else None,
            "cost_per_successful_workflow_usd": round(total_cost / len(completed), 6) if completed else None,
            "median_latency_ms": latencies[len(latencies) // 2] if latencies else None,
            "p95_latency_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None,
            "token_consumption": sum(a.prompt_tokens + a.completion_tokens for a in ars),
            "tool_executions": len(tools),
            "tool_failure_rate": round(sum(1 for t in tools if t.status in {"failed", "dead_letter"}) / len(tools), 4) if tools else None,
            "side_effect_actions": len(side_effects),
            "duplicate_actions_suppressed": dup_suppressed,
            "duplicate_external_action_rate": 0.0 if side_effects else None,
            "validation_failures": sum(1 for a in ars if (a.error or {}).get("code") in {"validation_failed", "agent_output_invalid", "llm_output_invalid"}),
            "approvals_requested": len(approvals),
            "approval_rate": round(sum(1 for a in decided if a.status in {"approved", "executed"}) / len(decided), 4) if decided else None,
            "approval_latency_minutes_avg": round(sum(approval_latency) / len(approval_latency), 2) if approval_latency else None,
            "human_intervention_rate": round(sum(1 for a in ars if a.status in {"needs_approval", "needs_input"}) / len(ars), 4) if ars else None,
        },
        "roi": {
            "assumptions": roi,
            "estimated_minutes_saved": round(minutes, 1),
            "estimated_labor_value_usd": round(labor_value, 2),
            "realized_savings_usd": round(labor_value * roi["realization_rate"], 2),
            "ai_cost_usd": round(total_cost, 4),
            "infra_cost_usd": round(infra, 4),
            "net_estimated_value_usd": round(labor_value - total_cost - infra, 2),
            "note": "Estimated labor value is time saved × loaded hourly cost. It is NOT realized savings; realized savings apply the finance-verified realization rate.",
        },
        "agents": agent_rows,
        "workflows": _per_workflow(runs),
    }


def _per_workflow(runs: list[WorkflowRun]) -> list[dict[str, Any]]:
    agg: dict[str, dict[str, Any]] = {}
    for r in runs:
        a = agg.setdefault(r.workflow_key, {"workflow_key": r.workflow_key, "runs": 0, "completed": 0, "failed": 0, "waiting": 0, "cost_usd": 0.0, "minutes_saved": 0.0})
        a["runs"] += 1
        a["cost_usd"] = round(a["cost_usd"] + r.cost_usd, 6)
        if r.status == "completed":
            a["completed"] += 1
            a["minutes_saved"] = round(a["minutes_saved"] + r.estimated_minutes_saved, 2)
        elif r.status in {"failed", "timed_out"}:
            a["failed"] += 1
        elif r.status in {"waiting_approval", "waiting_input"}:
            a["waiting"] += 1
    return sorted(agg.values(), key=lambda x: -x["runs"])


@router.get("/usage", summary="Usage and quota for the current billing period")
def usage(period: str | None = None, principal: Principal = Depends(require("usage:read")), db: Session = Depends(get_db)) -> dict[str, Any]:
    totals = period_totals(db, principal.tenant.id, period)
    quotas = tenant_quotas(principal.tenant)
    used_runs = totals["totals"]["workflow_run"]["quantity"]
    used_tokens = totals["totals"]["llm_tokens"]["quantity"]
    return {
        **totals,
        "plan": principal.tenant.plan,
        "quotas": quotas,
        "utilization": {
            "workflow_runs": round(used_runs / quotas["monthly_workflow_runs"], 4) if quotas["monthly_workflow_runs"] else None,
            "llm_tokens": round(used_tokens / quotas["monthly_llm_tokens"], 4) if quotas["monthly_llm_tokens"] else None,
        },
    }


@router.get("/audit-events", response_model=Page[AuditEventOut], summary="Search the audit trail")
def audit_events(
    q: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    severity: str | None = None,
    correlation_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require("audit:read")),
    db: Session = Depends(get_db),
) -> Page[AuditEventOut]:
    stmt = select(AuditEvent).where(AuditEvent.tenant_id == principal.tenant.id)
    if action:
        stmt = stmt.where(AuditEvent.action.startswith(action))
    if resource_type:
        stmt = stmt.where(AuditEvent.resource_type == resource_type)
    if severity:
        stmt = stmt.where(AuditEvent.severity == severity)
    if correlation_id:
        stmt = stmt.where(AuditEvent.correlation_id == correlation_id)
    if q:
        stmt = stmt.where(or_(AuditEvent.action.contains(q), AuditEvent.resource_id.contains(q), AuditEvent.actor_id.contains(q)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return Page(items=[audit_out(e) for e in rows], total=total, limit=limit, offset=offset)


@router.get("/audit-events/verify", summary="Verify the audit hash chain")
def audit_verify(principal: Principal = Depends(require("audit:read")), db: Session = Depends(get_db)) -> dict[str, Any]:
    return verify_chain(db, principal.tenant.id)


@router.get("/incidents", response_model=Page[IncidentOut], summary="Incidents")
def incidents(status: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), principal: Principal = Depends(require("reports:read")), db: Session = Depends(get_db)) -> Page[IncidentOut]:
    stmt = select(Incident).where(Incident.tenant_id == principal.tenant.id)
    if status:
        stmt = stmt.where(Incident.status == status)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Incident.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return Page(items=[incident_out(i) for i in rows], total=total, limit=limit, offset=offset)


@router.post("/incidents/{incident_id}/resolve", response_model=IncidentOut, summary="Resolve an incident")
def resolve_incident(incident_id: str, principal: Principal = Depends(require("incidents:write")), db: Session = Depends(get_db)) -> IncidentOut:
    import uuid

    inc = db.get(Incident, uuid.UUID(incident_id))
    if inc is None or inc.tenant_id != principal.tenant.id:
        raise NotFound("Incident not found")
    inc.status = "resolved"
    inc.resolved_at = datetime.now(UTC)
    from app.services.audit import record_audit

    record_audit(db, tenant_id=principal.tenant.id, action="incident.resolved", resource_type="incident", resource_id=str(inc.id), actor_id=principal.actor_id)
    db.commit()
    return incident_out(inc)
