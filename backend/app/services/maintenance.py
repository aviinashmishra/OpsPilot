"""Periodic maintenance: reconciliation, daily metrics, retention."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.agents.base import AgentContext
from app.agents.registry import resolve_spec
from app.core.logging import get_logger
from app.db.models import (
    AgentRun,
    Approval,
    AuditEvent,
    BusinessEvent,
    DailyMetric,
    Tenant,
    ToolExecution,
    WorkflowRun,
)
from app.services.actions import ActionService

log = get_logger("maintenance")


def reconcile_unknown_executions(db: Session, max_age_hours: int = 48) -> int:
    rows = db.execute(select(ToolExecution).where(ToolExecution.status == "unknown")).scalars().all()
    count = 0
    for rec in rows:
        tenant = db.get(Tenant, rec.tenant_id)
        if tenant is None:
            continue
        agent_key = None
        if rec.agent_run_id:
            ar = db.get(AgentRun, rec.agent_run_id)
            agent_key = ar.agent_key if ar else None
        spec = resolve_spec(agent_key)
        if spec is None:
            continue
        ctx = AgentContext(tenant_id=str(tenant.id), actor_id="system", workflow_run_id=str(rec.run_id) if rec.run_id else None, correlation_id=rec.correlation_id or "maintenance", permissions=["*"])
        ActionService(db, tenant, ctx, spec).reconcile(rec)
        count += 1
    return count


def _upsert_metric(db: Session, tenant_id: Any, day: date, key: str, value: float, agent_key: str = "", dims: dict[str, Any] | None = None) -> None:
    row = db.execute(
        select(DailyMetric).where(DailyMetric.tenant_id == tenant_id, DailyMetric.metric_date == day, DailyMetric.metric_key == key, DailyMetric.agent_key == agent_key)
    ).scalar_one_or_none()
    if row:
        row.value = value
        row.dimensions = dims or {}
    else:
        db.add(DailyMetric(tenant_id=tenant_id, metric_date=day, metric_key=key, agent_key=agent_key, value=value, dimensions=dims or {}))


def compute_daily_metrics(db: Session, day: date | None = None) -> int:
    day = day or datetime.now(UTC).date()
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    end = start + timedelta(days=1)
    written = 0
    for tenant in db.execute(select(Tenant)).scalars().all():
        runs = db.execute(select(WorkflowRun).where(WorkflowRun.tenant_id == tenant.id, WorkflowRun.created_at >= start, WorkflowRun.created_at < end)).scalars().all()
        total = len(runs)
        completed = sum(1 for r in runs if r.status == "completed")
        failed = sum(1 for r in runs if r.status in {"failed", "timed_out"})
        cost = sum(r.cost_usd for r in runs)
        minutes = sum(r.estimated_minutes_saved for r in runs if r.status == "completed")
        _upsert_metric(db, tenant.id, day, "workflow_runs", total)
        _upsert_metric(db, tenant.id, day, "workflow_completed", completed)
        _upsert_metric(db, tenant.id, day, "workflow_failed", failed)
        _upsert_metric(db, tenant.id, day, "workflow_completion_rate", (completed / total) if total else 0.0)
        _upsert_metric(db, tenant.id, day, "ai_cost_usd", round(cost, 6))
        _upsert_metric(db, tenant.id, day, "cost_per_successful_workflow", round(cost / completed, 6) if completed else 0.0)
        _upsert_metric(db, tenant.id, day, "estimated_minutes_saved", round(minutes, 2))
        latencies = sorted((r.finished_at - r.started_at).total_seconds() * 1000 for r in runs if r.started_at and r.finished_at)
        if latencies:
            _upsert_metric(db, tenant.id, day, "latency_p50_ms", latencies[len(latencies) // 2])
            _upsert_metric(db, tenant.id, day, "latency_p95_ms", latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))])
        written += 9

        agent_rows = db.execute(
            select(AgentRun.agent_key, AgentRun.status, func.count(), func.sum(AgentRun.cost_usd), func.avg(AgentRun.latency_ms))
            .where(AgentRun.tenant_id == tenant.id, AgentRun.created_at >= start, AgentRun.created_at < end)
            .group_by(AgentRun.agent_key, AgentRun.status)
        ).all()
        per_agent: dict[str, dict[str, Any]] = {}
        for key, status, n, c, lat in agent_rows:
            a = per_agent.setdefault(key, {"total": 0, "ok": 0, "failed": 0, "needs_approval": 0, "cost": 0.0, "latency": 0.0})
            a["total"] += n
            a["cost"] += float(c or 0)
            a["latency"] = float(lat or 0)
            if status in {"completed", "needs_approval"}:
                a["ok"] += n
            if status == "needs_approval":
                a["needs_approval"] += n
            if status == "failed":
                a["failed"] += n
        for key, a in per_agent.items():
            _upsert_metric(db, tenant.id, day, "agent_runs", a["total"], key)
            _upsert_metric(db, tenant.id, day, "agent_success_rate", a["ok"] / a["total"] if a["total"] else 0.0, key)
            _upsert_metric(db, tenant.id, day, "agent_cost_usd", round(a["cost"], 6), key)
            _upsert_metric(db, tenant.id, day, "agent_latency_ms", round(a["latency"], 1), key)
            _upsert_metric(db, tenant.id, day, "human_intervention_rate", a["needs_approval"] / a["total"] if a["total"] else 0.0, key)
            written += 5

        approvals = db.execute(select(Approval).where(Approval.tenant_id == tenant.id, Approval.decided_at >= start, Approval.decided_at < end)).scalars().all()
        if approvals:
            lat = [(a.decided_at - a.created_at).total_seconds() / 60 for a in approvals if a.decided_at]
            _upsert_metric(db, tenant.id, day, "approval_latency_minutes_avg", round(sum(lat) / len(lat), 2) if lat else 0.0)
            written += 1
        tools = db.execute(select(ToolExecution.status, func.count()).where(ToolExecution.tenant_id == tenant.id, ToolExecution.created_at >= start, ToolExecution.created_at < end).group_by(ToolExecution.status)).all()
        tcount = {s: n for s, n in tools}
        ttotal = sum(tcount.values())
        if ttotal:
            _upsert_metric(db, tenant.id, day, "tool_failure_rate", (tcount.get("failed", 0) + tcount.get("dead_letter", 0)) / ttotal)
            written += 1
    db.flush()
    return written


def apply_retention(db: Session) -> int:
    """Delete expired operational data per tenant retention policy (audit events are kept longer)."""
    purged = 0
    for tenant in db.execute(select(Tenant)).scalars().all():
        days = int(tenant.retention_days or 365)
        cutoff = datetime.now(UTC) - timedelta(days=days)
        purged += db.execute(delete(BusinessEvent).where(BusinessEvent.tenant_id == tenant.id, BusinessEvent.created_at < cutoff)).rowcount or 0
        audit_cutoff = datetime.now(UTC) - timedelta(days=max(days * 2, 730))
        try:
            # Savepoint: on PostgreSQL the application role has no DELETE on audit_events (append-only);
            # purging the audit trail is then a DBA task run as the owner role.
            with db.begin_nested():
                purged += db.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant.id, AuditEvent.created_at < audit_cutoff)).rowcount or 0
        except DBAPIError as exc:
            log.warning("retention.audit_purge_skipped", tenant_id=str(tenant.id), reason=str(exc.orig)[:200])
    db.flush()
    return purged
