"""ORM -> API schema conversion with sensitive-data redaction."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.api import schemas as s
from app.core.logging import redact
from app.db import models as m
from app.integrations.mock_adapters import MOCK_ADAPTERS, PROVIDER_FAMILIES
from app.tools.registry import tool_registry

_SENSITIVE_INPUT_KEYS = {"transcript", "document_text", "body", "message", "text"}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def redact_for_viewer(data: Any, can_view_sensitive: bool) -> Any:
    """Secrets are always redacted; long free-text fields are truncated for non-privileged viewers."""
    data = redact(data)
    if can_view_sensitive:
        return data
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if k in _SENSITIVE_INPUT_KEYS and isinstance(v, str) and len(v) > 280:
                out[k] = v[:280] + f"… [{len(v) - 280} chars hidden]"
            else:
                out[k] = redact_for_viewer(v, can_view_sensitive)
        return out
    if isinstance(data, list):
        return [redact_for_viewer(v, can_view_sensitive) for v in data]
    return data


def tenant_out(t: m.Tenant) -> s.TenantOut:
    return s.TenantOut(
        id=str(t.id), slug=t.slug, name=t.name, plan=t.plan, status=t.status, emergency_disabled=t.emergency_disabled,
        retention_days=t.retention_days, settings=t.settings or {}, quotas=t.quotas or {}, feature_flags=t.feature_flags or {},
    )


def user_out(u: m.User) -> s.UserOut:
    perms: set[str] = set()
    for r in u.roles:
        perms.update(r.permissions or [])
    return s.UserOut(id=str(u.id), email=u.email, full_name=u.full_name, roles=[r.name for r in u.roles], permissions=sorted(perms), is_active=u.is_active)


def checkpoint_out(c: m.WorkflowCheckpoint) -> s.CheckpointOut:
    return s.CheckpointOut(sequence=c.sequence, node_key=c.node_key, node_type=c.node_type, status=c.status, detail=c.detail or {}, duration_ms=c.duration_ms, created_at=_aware(c.created_at))  # type: ignore[arg-type]


def agent_run_out(a: m.AgentRun, sensitive: bool = True) -> s.AgentRunOut:
    return s.AgentRunOut(
        id=str(a.id), agent_key=a.agent_key, agent_version=a.agent_version, node_key=a.node_key, status=a.status,
        input=redact_for_viewer(a.input or {}, sensitive), output=redact_for_viewer(a.output or {}, sensitive),
        evidence_refs=a.evidence_refs or [], missing_information=a.missing_information or [],
        proposed_actions=redact_for_viewer(a.proposed_actions or [], sensitive), warnings=a.warnings or [], model=a.model,
        prompt_tokens=a.prompt_tokens, completion_tokens=a.completion_tokens, cost_usd=a.cost_usd, latency_ms=a.latency_ms,
        error=a.error, started_at=_aware(a.started_at), finished_at=_aware(a.finished_at),  # type: ignore[arg-type]
    )


def run_out(r: m.WorkflowRun, *, detailed: bool = False, sensitive: bool = True, pending: list[str] | None = None, graph: dict | None = None) -> s.WorkflowRunOut:
    state = dict(r.state or {})
    state.pop("permissions", None)
    return s.WorkflowRunOut(
        id=str(r.id), workflow_key=r.workflow_key, workflow_version=r.workflow_version, status=r.status, correlation_id=r.correlation_id,
        actor_id=r.actor_id, current_node=r.current_node, step_count=r.step_count, attempt=r.attempt,
        input=redact_for_viewer(r.input or {}, sensitive), output=redact_for_viewer(r.output or {}, sensitive) if detailed else {},
        state=redact_for_viewer(state, sensitive) if detailed else {}, error=r.error, cost_usd=r.cost_usd,
        estimated_minutes_saved=r.estimated_minutes_saved, cancel_requested=r.cancel_requested,
        parent_run_id=str(r.parent_run_id) if r.parent_run_id else None, depth=r.depth, created_at=_aware(r.created_at),  # type: ignore[arg-type]
        started_at=_aware(r.started_at), finished_at=_aware(r.finished_at), deadline_at=_aware(r.deadline_at),
        checkpoints=[checkpoint_out(c) for c in r.checkpoints] if detailed else [],
        agent_runs=[agent_run_out(a, sensitive) for a in sorted(r.agent_runs, key=lambda x: x.started_at)] if detailed else [],
        pending_approvals=pending or [], graph=graph,
    )


def task_out(t: m.Task) -> s.TaskOut:
    now = datetime.now(UTC)
    due = _aware(t.due_at)
    return s.TaskOut(
        id=str(t.id), title=t.title, description=t.description, status=t.status, priority=t.priority,
        owner_user_id=str(t.owner_user_id) if t.owner_user_id else None, owner_name=t.owner_name, due_at=due, sla_hours=t.sla_hours,
        source=t.source, source_run_id=str(t.source_run_id) if t.source_run_id else None, evidence_refs=t.evidence_refs or [],
        labels=t.labels or [], depends_on=t.depends_on or [], escalation_level=t.escalation_level, created_by=t.created_by,
        created_at=_aware(t.created_at), updated_at=_aware(t.updated_at), completed_at=_aware(t.completed_at),  # type: ignore[arg-type]
        overdue=bool(due and due < now and t.status not in {"done", "cancelled"}),
    )


def approval_out(a: m.Approval, reviewer_name: str | None = None) -> s.ApprovalOut:
    return s.ApprovalOut(
        id=str(a.id), run_id=str(a.run_id) if a.run_id else None, agent_run_id=str(a.agent_run_id) if a.agent_run_id else None,
        agent_key=a.agent_key, node_key=a.node_key, action_type=a.action_type, tool_key=a.tool_key, action_payload=redact(a.action_payload or {}),
        payload_hash=a.payload_hash, context=redact(a.context or {}), evidence=a.evidence or [], reason=a.reason, risk_level=a.risk_level,
        policy_id=a.policy_id, policy_version=a.policy_version, status=a.status, requested_by=a.requested_by,
        required_permission=a.required_permission, reviewer_id=str(a.reviewer_id) if a.reviewer_id else None, reviewer_name=reviewer_name,
        decided_at=_aware(a.decided_at), decision_note=a.decision_note, expires_at=_aware(a.expires_at),  # type: ignore[arg-type]
        executed_at=_aware(a.executed_at), execution_result=a.execution_result, created_at=_aware(a.created_at),  # type: ignore[arg-type]
    )


def integration_out(i: m.Integration) -> s.IntegrationOut:
    fam = PROVIDER_FAMILIES.get(i.provider, {"label": i.provider})
    cfg = {k: v for k, v in (i.config or {}).items() if k != "live_provider"}
    return s.IntegrationOut(
        id=str(i.id), provider=i.provider, provider_label=fam.get("label", i.provider), name=i.name, mode=i.mode, status=i.status,
        live_provider=(i.config or {}).get("live_provider"), config=redact(cfg), scopes=i.scopes or [], has_credentials=bool(i.encrypted_credentials),
        has_webhook_secret=bool(i.webhook_secret_encrypted), last_sync_at=_aware(i.last_sync_at), last_test_at=_aware(i.last_test_at),
        last_test_ok=i.last_test_ok, last_error=i.last_error, health=i.health or {},
        capabilities=list(MOCK_ADAPTERS[i.provider].capabilities) if i.provider in MOCK_ADAPTERS else [],
        tools=[t.key for t in tool_registry.by_provider(i.provider)], created_at=_aware(i.created_at),  # type: ignore[arg-type]
    )


def audit_out(e: m.AuditEvent) -> s.AuditEventOut:
    return s.AuditEventOut(
        id=str(e.id), created_at=_aware(e.created_at), actor_id=e.actor_id, actor_type=e.actor_type, action=e.action,  # type: ignore[arg-type]
        resource_type=e.resource_type, resource_id=e.resource_id, correlation_id=e.correlation_id, details=e.details or {},
        severity=e.severity, hash=e.hash, seq=e.seq, prev_hash=e.prev_hash, chain_hash=e.chain_hash,
    )


def incident_out(i: m.Incident) -> s.IncidentOut:
    return s.IncidentOut(
        id=str(i.id), severity=i.severity, title=i.title, source=i.source, kind=i.kind, status=i.status, details=redact(i.details or {}),
        run_id=str(i.run_id) if i.run_id else None, created_at=_aware(i.created_at), resolved_at=_aware(i.resolved_at),  # type: ignore[arg-type]
    )


def document_out(d: m.Document) -> s.DocumentOut:
    return s.DocumentOut(
        id=str(d.id), name=d.name, collection=d.collection, content_type=d.content_type, size_bytes=d.size_bytes, sha256=d.sha256,
        classification=d.classification, scan_status=d.scan_status, scan_findings=d.scan_findings or [], chunk_count=len(d.chunks),
        meta=d.meta or {}, created_at=_aware(d.created_at),  # type: ignore[arg-type]
    )
