"""Workflow runs and definitions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.schemas import Page, WorkflowDefinitionIn, WorkflowDefinitionOut, WorkflowRunOut, WorkflowStartIn
from app.api.serializers import run_out
from app.core.errors import Conflict, NotFound
from app.core.ratelimit import check_rate_limit
from app.core.security import canonical_hash
from app.db.models import Approval, IdempotencyRecord, WorkflowDefinition, WorkflowRun
from app.db.session import get_db
from app.orchestration.engine import execute_run, request_cancel, start_run, validate_graph
from app.services.audit import record_audit
from app.workers.queue import enqueue_run

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _get_run(db: Session, principal: Principal, run_id: str) -> WorkflowRun:
    try:
        rid = uuid.UUID(run_id)
    except ValueError as exc:
        raise NotFound("Workflow run not found") from exc
    run = db.get(WorkflowRun, rid)
    if run is None or run.tenant_id != principal.tenant.id:
        raise NotFound("Workflow run not found")
    return run


def _definition_out(d: WorkflowDefinition) -> WorkflowDefinitionOut:
    return WorkflowDefinitionOut(
        id=str(d.id), key=d.key, name=d.name, description=d.description, version=d.version, graph=d.graph, trigger=d.trigger,
        is_active=d.is_active, timeout_seconds=d.timeout_seconds, scope="tenant" if d.tenant_id else "platform",
    )


@router.post("", response_model=WorkflowRunOut, status_code=202, summary="Start a workflow run (idempotent with Idempotency-Key)")
def create_workflow_run(
    body: WorkflowStartIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require("workflows:write")),
    db: Session = Depends(get_db),
) -> WorkflowRunOut:
    check_rate_limit(f"workflows:{principal.tenant.id}")
    if idempotency_key:
        req_hash = canonical_hash(body.model_dump())
        rec = db.execute(select(IdempotencyRecord).where(IdempotencyRecord.tenant_id == principal.tenant.id, IdempotencyRecord.scope == "workflows.create", IdempotencyRecord.key == idempotency_key)).scalar_one_or_none()
        if rec and rec.request_hash != req_hash:
            raise Conflict("Idempotency-Key reused with a different request body")
    run = start_run(db, tenant_id=str(principal.tenant.id), workflow_key=body.workflow_key, input=body.input, actor_id=principal.actor_id, idempotency_key=idempotency_key, permissions=principal.permissions if not principal.is_admin else None, validate_input=True)
    if idempotency_key:
        exists = db.execute(select(IdempotencyRecord).where(IdempotencyRecord.tenant_id == principal.tenant.id, IdempotencyRecord.scope == "workflows.create", IdempotencyRecord.key == idempotency_key)).scalar_one_or_none()
        if not exists:
            db.add(IdempotencyRecord(tenant_id=principal.tenant.id, scope="workflows.create", key=idempotency_key, request_hash=canonical_hash(body.model_dump()), response={"run_id": str(run.id)}, status_code=202))
            db.commit()
    db.refresh(run)
    return run_out(run)


@router.get("", response_model=Page[WorkflowRunOut], summary="List workflow runs")
def list_runs(
    status: str | None = None,
    workflow_key: str | None = None,
    q: str | None = Query(default=None, description="Search by run id or correlation id"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require("workflows:read")),
    db: Session = Depends(get_db),
) -> Page[WorkflowRunOut]:
    stmt = select(WorkflowRun).where(WorkflowRun.tenant_id == principal.tenant.id)
    if status:
        stmt = stmt.where(WorkflowRun.status.in_(status.split(",")))
    if workflow_key:
        stmt = stmt.where(WorkflowRun.workflow_key == workflow_key)
    if q:
        try:
            stmt = stmt.where(or_(WorkflowRun.correlation_id.contains(q), WorkflowRun.id == uuid.UUID(q)))
        except ValueError:
            stmt = stmt.where(or_(WorkflowRun.correlation_id.contains(q), WorkflowRun.workflow_key.contains(q)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(WorkflowRun.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return Page(items=[run_out(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/definitions", response_model=list[WorkflowDefinitionOut], summary="List workflow definitions")
def list_definitions(principal: Principal = Depends(require("workflows:read")), db: Session = Depends(get_db)) -> list[WorkflowDefinitionOut]:
    rows = db.execute(
        select(WorkflowDefinition).where(or_(WorkflowDefinition.tenant_id.is_(None), WorkflowDefinition.tenant_id == principal.tenant.id)).order_by(WorkflowDefinition.key)
    ).scalars().all()
    return [_definition_out(d) for d in rows]


@router.post("/definitions", response_model=WorkflowDefinitionOut, status_code=201, summary="Create or version a tenant workflow definition")
def create_definition(body: WorkflowDefinitionIn, principal: Principal = Depends(require("workflows:admin")), db: Session = Depends(get_db)) -> WorkflowDefinitionOut:
    validate_graph(body.graph)
    from app.agents.registry import agent_registry

    for key, node in body.graph["nodes"].items():
        if node.get("type") == "agent" and not agent_registry.has(node.get("agent", "")):
            raise NotFound(f"Node '{key}' references unknown agent '{node.get('agent')}'")
    latest = db.execute(select(func.max(WorkflowDefinition.version)).where(WorkflowDefinition.tenant_id == principal.tenant.id, WorkflowDefinition.key == body.key)).scalar_one()
    d = WorkflowDefinition(tenant_id=principal.tenant.id, key=body.key, name=body.name, description=body.description, version=(latest or 0) + 1, graph=body.graph, trigger=body.trigger, timeout_seconds=body.timeout_seconds)
    db.add(d)
    db.flush()
    record_audit(db, tenant_id=principal.tenant.id, action="workflow_definition.created", resource_type="workflow_definition", resource_id=str(d.id), actor_id=principal.actor_id, details={"key": body.key, "version": d.version})
    db.commit()
    return _definition_out(d)


@router.get("/{run_id}", response_model=WorkflowRunOut, summary="Get a workflow run with checkpoints and agent runs")
def get_run(run_id: str, principal: Principal = Depends(require("workflows:read")), db: Session = Depends(get_db)) -> WorkflowRunOut:
    run = _get_run(db, principal, run_id)
    pending = [str(a.id) for a in db.execute(select(Approval).where(Approval.run_id == run.id, Approval.status == "pending")).scalars().all()]
    definition = db.get(WorkflowDefinition, run.workflow_definition_id) if run.workflow_definition_id else None
    return run_out(run, detailed=True, sensitive=principal.has("data:sensitive"), pending=pending, graph=definition.graph if definition else None)


@router.post("/{run_id}/cancel", response_model=WorkflowRunOut, summary="Cancel a workflow run")
def cancel_run(run_id: str, principal: Principal = Depends(require("workflows:write")), db: Session = Depends(get_db)) -> WorkflowRunOut:
    run = _get_run(db, principal, run_id)
    request_cancel(db, run, principal.actor_id)
    db.refresh(run)
    return run_out(run, detailed=True)


@router.post("/{run_id}/retry", response_model=WorkflowRunOut, summary="Retry a failed or timed-out run from its last checkpoint")
def retry_run(run_id: str, principal: Principal = Depends(require("workflows:write")), db: Session = Depends(get_db)) -> WorkflowRunOut:
    run = _get_run(db, principal, run_id)
    if run.status not in {"failed", "timed_out"}:
        raise Conflict(f"Only failed or timed-out runs can be retried (status={run.status})")
    from datetime import UTC, datetime, timedelta

    run.status = "pending"
    run.error = None
    run.finished_at = None
    run.attempt = 0
    run.deadline_at = datetime.now(UTC) + timedelta(seconds=600)
    record_audit(db, tenant_id=principal.tenant.id, action="workflow.retry", resource_type="workflow_run", resource_id=str(run.id), actor_id=principal.actor_id, details={"from_node": run.current_node}, correlation_id=run.correlation_id)
    db.commit()
    enqueue_run(str(run.id))
    db.refresh(run)
    return run_out(run, detailed=True)


execute_run  # noqa: B018 - exposed for scripts
