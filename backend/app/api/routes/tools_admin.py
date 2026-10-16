"""Tool catalog, tenant custom tools, bulk agent runs and the job queue (system) view."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.schemas import Page
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.security import encrypt_secret
from app.db.models import AgentBatch, AgentBatchItem, CustomTool, Job, ToolExecution, WorkerHeartbeat
from app.db.session import get_db
from app.services import batches as batch_svc
from app.services.audit import record_audit
from app.tools import custom as custom_tools
from app.tools.registry import tool_registry
from app.workers import jobs as jq

router = APIRouter(tags=["tools"])


# ---------------------------------------------------------------------------
# Tool catalog
# ---------------------------------------------------------------------------


@router.get("/tools", summary="Every tool agents can use (built-in + this tenant's custom tools)")
def tool_catalog(principal: Principal = Depends(require("agents:read")), db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.agents.registry import agent_registry

    used_by: dict[str, list[str]] = {}
    for a in agent_registry.all():
        for t in a.spec.allowed_tools:
            used_by.setdefault(t, []).append(a.spec.key)
    since = datetime.now(UTC) - timedelta(days=30)
    calls = dict(db.execute(select(ToolExecution.tool_key, func.count()).where(ToolExecution.tenant_id == principal.tenant.id, ToolExecution.created_at >= since).group_by(ToolExecution.tool_key)).all())
    builtin = [{**t.describe(), "used_by": used_by.get(t.key, []), "calls_30d": calls.get(t.key, 0), "source": "builtin"} for t in tool_registry.all()]
    custom = [{**_custom_out(c), "source": "custom", "calls_30d": calls.get(f"custom.{c.name}", 0)} for c in db.execute(select(CustomTool).where(CustomTool.tenant_id == principal.tenant.id).order_by(CustomTool.name)).scalars().all()]
    return {"builtin": builtin, "custom": custom, "providers": sorted({t["provider"] for t in builtin})}


# ---------------------------------------------------------------------------
# Custom tools
# ---------------------------------------------------------------------------


class CustomToolIn(BaseModel):
    name: str = Field(min_length=2, max_length=48)
    description: str = Field(min_length=5, max_length=1000)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    url_template: str = Field(max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict)
    auth_header_name: str | None = Field(default=None, max_length=100)
    auth_secret: str | None = Field(default=None, max_length=4000, description="Write-only; stored encrypted")
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    side_effect: bool = False
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    timeout_seconds: int = Field(default=15, ge=1, le=60)
    enabled: bool = True


class CustomToolPatch(BaseModel):
    description: str | None = None
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] | None = None
    url_template: str | None = None
    headers: dict[str, str] | None = None
    auth_header_name: str | None = None
    auth_secret: str | None = None
    input_schema: dict[str, Any] | None = None
    side_effect: bool | None = None
    risk_level: Literal["low", "medium", "high", "critical"] | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    enabled: bool | None = None


class CustomToolTestIn(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    confirm_side_effect: bool = False


def _custom_out(c: CustomTool) -> dict[str, Any]:
    return {
        "id": str(c.id), "key": f"custom.{c.name}", "name": c.name, "description": c.description, "method": c.method, "url_template": c.url_template,
        "headers": c.headers or {}, "auth_header_name": c.auth_header_name, "has_secret": bool(c.auth_secret_encrypted), "input_schema": c.input_schema or {},
        "side_effect": c.side_effect, "risk_level": c.risk_level, "timeout_seconds": c.timeout_seconds, "enabled": c.enabled,
        "call_count": c.call_count, "last_called_at": _iso(c.last_called_at), "created_at": _iso(c.created_at),
    }


def _get_custom(db: Session, principal: Principal, tool_id: str) -> CustomTool:
    try:
        row = db.get(CustomTool, uuid.UUID(tool_id))
    except ValueError as exc:
        raise NotFound("Custom tool not found") from exc
    if row is None or row.tenant_id != principal.tenant.id:
        raise NotFound("Custom tool not found")
    return row


@router.get("/custom-tools", summary="List this tenant's custom HTTP tools")
def list_custom(principal: Principal = Depends(require("integrations:read")), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [_custom_out(c) for c in db.execute(select(CustomTool).where(CustomTool.tenant_id == principal.tenant.id).order_by(CustomTool.name)).scalars().all()]


@router.post("/custom-tools", status_code=201, summary="Register a custom HTTP tool")
def create_custom(body: CustomToolIn, principal: Principal = Depends(require("integrations:admin")), db: Session = Depends(get_db)) -> dict[str, Any]:
    custom_tools.validate_definition(body.name, body.method, body.url_template, body.input_schema)
    if db.execute(select(CustomTool).where(CustomTool.tenant_id == principal.tenant.id, CustomTool.name == body.name)).scalar_one_or_none():
        raise Conflict(f"A custom tool named '{body.name}' already exists")
    if body.side_effect and body.risk_level == "low":
        body.risk_level = "medium"
    row = CustomTool(
        tenant_id=principal.tenant.id, name=body.name, description=body.description, method=body.method, url_template=body.url_template, headers=body.headers,
        auth_header_name=body.auth_header_name, auth_secret_encrypted=encrypt_secret(body.auth_secret) if body.auth_secret else None, input_schema=body.input_schema,
        side_effect=body.side_effect, risk_level=body.risk_level, timeout_seconds=body.timeout_seconds, enabled=body.enabled, created_by=principal.actor_id,
    )
    db.add(row)
    db.flush()
    record_audit(db, tenant_id=principal.tenant.id, action="custom_tool.created", resource_type="custom_tool", resource_id=str(row.id), actor_id=principal.actor_id, details={"name": row.name, "method": row.method, "host": row.url_template.split("/")[2] if "//" in row.url_template else None, "side_effect": row.side_effect})
    db.commit()
    return _custom_out(row)


@router.patch("/custom-tools/{tool_id}", summary="Update a custom tool")
def update_custom(tool_id: str, body: CustomToolPatch, principal: Principal = Depends(require("integrations:admin")), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _get_custom(db, principal, tool_id)
    data = body.model_dump(exclude_unset=True)
    secret = data.pop("auth_secret", None)
    for k, v in data.items():
        setattr(row, k, v)
    custom_tools.validate_definition(row.name, row.method, row.url_template, row.input_schema or {})
    if secret is not None:
        row.auth_secret_encrypted = encrypt_secret(secret) if secret else None
    if row.side_effect and row.risk_level == "low":
        row.risk_level = "medium"
    record_audit(db, tenant_id=principal.tenant.id, action="custom_tool.updated", resource_type="custom_tool", resource_id=str(row.id), actor_id=principal.actor_id, details={"fields": sorted(data), "secret_changed": secret is not None})
    db.commit()
    return _custom_out(row)


@router.delete("/custom-tools/{tool_id}", status_code=204, response_class=Response, summary="Delete a custom tool")
def delete_custom(tool_id: str, principal: Principal = Depends(require("integrations:admin")), db: Session = Depends(get_db)) -> Response:
    row = _get_custom(db, principal, tool_id)
    record_audit(db, tenant_id=principal.tenant.id, action="custom_tool.deleted", resource_type="custom_tool", resource_id=str(row.id), actor_id=principal.actor_id, details={"name": row.name}, severity="warning")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.post("/custom-tools/{tool_id}/test", summary="Call a custom tool once with sample input (real HTTP request)")
def test_custom(tool_id: str, body: CustomToolTestIn, principal: Principal = Depends(require("integrations:admin")), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _get_custom(db, principal, tool_id)
    if row.side_effect and not body.confirm_side_effect:
        raise ValidationFailed("This tool has side effects; set confirm_side_effect=true to send a real request")
    started = datetime.now(UTC)
    try:
        result = custom_tools.execute(row, body.input)
        ok, error = True, None
    except Exception as exc:  # noqa: BLE001
        result, ok, error = None, False, getattr(exc, "message", None) or str(exc)
    ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    record_audit(db, tenant_id=principal.tenant.id, action="custom_tool.tested", resource_type="custom_tool", resource_id=str(row.id), actor_id=principal.actor_id, details={"ok": ok, "error": error, "ms": ms}, severity="info" if ok else "warning")
    db.commit()
    return {"ok": ok, "latency_ms": ms, "result": result, "error": error}


# ---------------------------------------------------------------------------
# Bulk agent runs
# ---------------------------------------------------------------------------


class BatchIn(BaseModel):
    items: list[dict[str, Any]] = Field(min_length=1, max_length=batch_svc.MAX_ITEMS)
    name: str | None = Field(default=None, max_length=200)
    execute_actions: bool = True


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=UTC))


def _iso(dt: datetime | None) -> str | None:
    """Always timezone-explicit (SQLite returns naive datetimes; they are UTC)."""
    return None if dt is None else _aware(dt).astimezone(UTC).isoformat().replace("+00:00", "Z")


def _batch_out(b: AgentBatch) -> dict[str, Any]:
    done = b.succeeded + b.failed + b.needs_review
    started, finished = _aware(b.created_at), _aware(b.finished_at)
    return {
        "id": str(b.id), "agent_key": b.agent_key, "name": b.name, "status": b.status, "total": b.total, "succeeded": b.succeeded, "failed": b.failed, "needs_review": b.needs_review,
        "processed": done, "progress": round(done / b.total, 4) if b.total else 1.0, "execute_actions": b.execute_actions, "created_by": b.created_by,
        "correlation_id": b.correlation_id, "cost_usd": round(b.cost_usd, 6), "created_at": _iso(b.created_at), "finished_at": _iso(b.finished_at),
        "elapsed_seconds": round(((finished or datetime.now(UTC)) - started).total_seconds(), 1) if started else None,
    }


@router.post("/agents/{agent_id}/batches", status_code=202, summary="Run an agent over many inputs (fan-out through the job queue)")
def create_batch(agent_id: str, body: BatchIn, principal: Principal = Depends(require("agents:run")), db: Session = Depends(get_db)) -> dict[str, Any]:
    b = batch_svc.create_batch(db, tenant=principal.tenant, agent_key=agent_id, items=body.items, actor_id=principal.actor_id, name=body.name, execute_actions=body.execute_actions)
    db.refresh(b)
    return _batch_out(b)


@router.get("/batches", summary="Bulk runs")
def list_batches(agent_key: str | None = None, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0), principal: Principal = Depends(require("agents:read")), db: Session = Depends(get_db)) -> Page[dict[str, Any]]:
    stmt = select(AgentBatch).where(AgentBatch.tenant_id == principal.tenant.id)
    if agent_key:
        stmt = stmt.where(AgentBatch.agent_key == agent_key)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(AgentBatch.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return Page(items=[_batch_out(b) for b in rows], total=total, limit=limit, offset=offset)


def _uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound(f"{what} not found") from exc


@router.get("/batches/{batch_id}", summary="Bulk run progress and item results")
def get_batch(batch_id: str, status: str | None = None, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), principal: Principal = Depends(require("agents:read")), db: Session = Depends(get_db)) -> dict[str, Any]:
    b = db.get(AgentBatch, _uuid(batch_id, "Batch"))
    if b is None or b.tenant_id != principal.tenant.id:
        raise NotFound("Batch not found")
    stmt = select(AgentBatchItem).where(AgentBatchItem.batch_id == b.id)
    if status:
        stmt = stmt.where(AgentBatchItem.status == status)
    items = db.execute(stmt.order_by(AgentBatchItem.item_index).limit(limit).offset(offset)).scalars().all()
    return {
        **_batch_out(b),
        "items": [{"index": i.item_index, "status": i.status, "summary": i.summary, "error": i.error, "approval_ids": i.approval_ids, "agent_run_id": str(i.agent_run_id) if i.agent_run_id else None, "latency_ms": i.latency_ms, "input": i.input} for i in items],
        "items_limit": limit, "items_offset": offset,
    }


@router.post("/batches/{batch_id}/cancel", summary="Cancel the remaining items of a bulk run")
def cancel_batch(batch_id: str, principal: Principal = Depends(require("agents:run")), db: Session = Depends(get_db)) -> dict[str, Any]:
    b = db.get(AgentBatch, _uuid(batch_id, "Batch"))
    if b is None or b.tenant_id != principal.tenant.id:
        raise NotFound("Batch not found")
    return _batch_out(batch_svc.cancel_batch(db, b))


# ---------------------------------------------------------------------------
# System: job queue and workers
# ---------------------------------------------------------------------------


@router.get("/system/queue", summary="Job queue depth, workers and recent jobs")
def system_queue(principal: Principal = Depends(require("reports:read")), db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.core.config import get_settings

    stats = jq.queue_stats(db, tenant_id=principal.tenant.id)  # counts are this tenant's jobs only
    now = datetime.now(UTC)
    workers = []
    for w in db.execute(select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()).limit(50)).scalars().all():
        seen = w.last_seen_at if w.last_seen_at.tzinfo else w.last_seen_at.replace(tzinfo=UTC)
        alive = w.status == "running" and (now - seen).total_seconds() < 30
        workers.append({"name": w.name, "hostname": w.hostname, "pid": w.pid, "concurrency": w.concurrency, "active_jobs": w.active_jobs, "processed": w.processed, "failed": w.failed, "status": "alive" if alive else ("stopped" if w.status == "stopped" else "lost"), "last_seen_at": _iso(seen)})
    hour_ago = now - timedelta(hours=1)
    done_last_hour = db.execute(select(func.count()).select_from(Job).where(Job.tenant_id == principal.tenant.id, Job.status == "done", Job.finished_at >= hour_ago)).scalar_one()
    recent = db.execute(select(Job).where(Job.tenant_id == principal.tenant.id).order_by(Job.updated_at.desc()).limit(25)).scalars().all()
    return {
        "worker_mode": get_settings().worker_mode,
        **stats,
        "throughput_last_hour": done_last_hour,
        "workers": workers,
        "alive_workers": sum(1 for w in workers if w["status"] == "alive"),
        "total_concurrency": sum(w["concurrency"] for w in workers if w["status"] == "alive"),
        "recent_jobs": [{"id": str(j.id), "kind": j.kind, "status": j.status, "attempts": j.attempts, "max_attempts": j.max_attempts, "locked_by": j.locked_by, "last_error": (j.last_error or "")[-500:] or None, "created_at": _iso(j.created_at), "finished_at": _iso(j.finished_at)} for j in recent],
    }


@router.post("/system/jobs/{job_id}/retry", summary="Re-queue a dead job")
def retry_job(job_id: str, principal: Principal = Depends(require("tenant:admin")), db: Session = Depends(get_db)) -> dict[str, Any]:
    job = db.get(Job, _uuid(job_id, "Job"))
    # Tenant admins may only retry their own tenant's jobs; system jobs (no tenant) are for operators.
    if job is None or job.tenant_id != principal.tenant.id:
        raise NotFound("Job not found")
    if jq.retry_dead_job(db, job.id) is None:
        raise Conflict(f"Only dead or failed jobs can be retried (status={job.status})")
    record_audit(db, tenant_id=principal.tenant.id, action="job.retried", resource_type="job", resource_id=job_id, actor_id=principal.actor_id)
    db.commit()
    from app.workers.pool import get_local_pool

    if (pool := get_local_pool()) is not None:
        pool.wake()
    return {"id": job_id, "status": "queued"}
