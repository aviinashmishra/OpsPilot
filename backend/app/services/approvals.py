"""Human approval service.

Guarantees:
* An approval is bound to the exact action payload (SHA-256 of tool, type,
  payload, tenant, agent). Any change to the payload invalidates it.
* Only reviewers holding the required permission may decide.
* Separation of duties: the requester cannot approve their own request
  (configurable per tenant, on by default).
* Approvals expire; expired approvals cannot be executed.
* An approval executes at most once (status transition guard + tool
  idempotency key), even under concurrent decisions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentContext, ProposedAction
from app.agents.registry import resolve_spec
from app.core.errors import AuthorizationError, Conflict, NotFound, ValidationFailed
from app.core.security import canonical_hash
from app.db.models import Approval, Tenant, User
from app.services.actions import ActionOutcome, ActionService
from app.services.audit import record_audit


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def expire_stale_approvals(db: Session, tenant_id: str | uuid.UUID | None = None) -> int:
    now = datetime.now(UTC)
    stmt = select(Approval).where(Approval.status == "pending")
    if tenant_id:
        stmt = stmt.where(Approval.tenant_id == uuid.UUID(str(tenant_id)))
    expired: list[Approval] = []
    for ap in db.execute(stmt).scalars().all():
        if _aware(ap.expires_at) < now:
            ap.status = "expired"
            expired.append(ap)
            record_audit(db, tenant_id=ap.tenant_id, action="approval.expired", resource_type="approval", resource_id=str(ap.id), actor_type="system", details={"tool": ap.tool_key})
    db.flush()
    # An expired action is treated like a rejection: the workflow continues without it instead of
    # staying in waiting_approval forever.
    for ap in expired:
        _resume_workflow(db, ap)
    return len(expired)


def decide_approval(
    db: Session,
    *,
    tenant: Tenant,
    approval_id: str | uuid.UUID,
    reviewer: User,
    reviewer_permissions: list[str],
    decision: str,
    note: str | None = None,
    payload_hash_check: str | None = None,
) -> dict[str, Any]:
    approval = db.get(Approval, uuid.UUID(str(approval_id)))
    if approval is None or approval.tenant_id != tenant.id:
        raise NotFound("Approval not found")
    if decision not in {"approve", "reject"}:
        raise ValidationFailed("decision must be 'approve' or 'reject'")
    if approval.status != "pending":
        raise Conflict(f"Approval is already {approval.status}", details={"status": approval.status})
    if _aware(approval.expires_at) < datetime.now(UTC):
        approval.status = "expired"
        db.commit()
        _resume_workflow(db, approval)
        raise Conflict("Approval has expired", details={"expires_at": approval.expires_at.isoformat()})
    if decision == "approve" and tenant.emergency_disabled:
        raise Conflict("Agents are emergency-disabled for this tenant; approved actions cannot run until it is turned off. You can still reject.")

    # Authorisation of the reviewer -------------------------------------------
    perms = set(reviewer_permissions)
    required = approval.required_permission or "approvals:decide"
    if "*" not in perms and required not in perms and "approvals:decide" not in perms:
        raise AuthorizationError(f"Reviewer lacks '{required}'")
    if "*" not in perms and required != "approvals:decide" and required not in perms and f"{required.split(':')[0]}:*" not in perms:
        raise AuthorizationError(f"Reviewer lacks '{required}'")
    sod = (tenant.settings.get("policies", {}) or {}).get("separation_of_duties", True)
    if sod and approval.requested_by and approval.requested_by == str(reviewer.id):
        raise AuthorizationError("Separation of duties: the requester cannot review their own request")

    # Tamper check: the stored payload must still hash to the bound hash --------
    bound = {"tool_key": approval.tool_key, "action_type": approval.action_type, "payload": approval.action_payload, "tenant_id": str(tenant.id), "agent_key": approval.agent_key}
    if canonical_hash(bound) != approval.payload_hash:
        approval.status = "superseded"
        db.flush()
        record_audit(db, tenant_id=tenant.id, action="approval.tampered", resource_type="approval", resource_id=str(approval.id), actor_id=str(reviewer.id), severity="critical", details={"reason": "payload hash mismatch"})
        db.commit()  # persist the supersede + audit even though the request fails
        raise Conflict("Approval payload no longer matches its bound hash; a new approval is required")
    if payload_hash_check and payload_hash_check != approval.payload_hash:
        raise Conflict("The action was modified after this approval was requested; re-request approval", details={"expected": approval.payload_hash})

    approval.reviewer_id = reviewer.id
    approval.decided_at = datetime.now(UTC)
    approval.decision_note = note

    if decision == "reject":
        approval.status = "rejected"
        db.flush()
        record_audit(db, tenant_id=tenant.id, action="approval.rejected", resource_type="approval", resource_id=str(approval.id), actor_id=str(reviewer.id), details={"tool": approval.tool_key, "note": note})
        db.commit()
        _resume_workflow(db, approval)
        return {"approval_id": str(approval.id), "status": "rejected"}

    # Approve -> execute exactly once ------------------------------------------
    approval.status = "approved"
    db.flush()
    db.commit()
    record_audit(db, tenant_id=tenant.id, action="approval.approved", resource_type="approval", resource_id=str(approval.id), actor_id=str(reviewer.id), details={"tool": approval.tool_key, "note": note})

    agent_spec = resolve_spec(approval.agent_key)
    if agent_spec is None:
        approval.status = "execution_failed"
        approval.execution_result = {"error": "agent no longer registered"}
        db.commit()
        raise Conflict("Agent for this approval is not registered")

    ctx = AgentContext(
        tenant_id=str(tenant.id),
        actor_id=str(reviewer.id),
        workflow_run_id=str(approval.run_id) if approval.run_id else None,
        agent_run_id=str(approval.agent_run_id) if approval.agent_run_id else None,
        correlation_id=str(approval.context.get("correlation_id") or approval.id),
        permissions=sorted(perms),
        policy_version=approval.policy_version or "v1",
        node_key=approval.node_key,
    )
    svc = ActionService(db, tenant, ctx, agent_spec, agent_run_id=ctx.agent_run_id)
    action = ProposedAction(
        action_type=approval.action_type,
        tool_key=approval.tool_key or "",
        payload=approval.action_payload,
        reason=str(approval.context.get("agent_reason", "")),
        risk_level=approval.risk_level,  # type: ignore[arg-type]
        idempotency_key=approval.action_payload.get("idempotency_key") or f"approval:{approval.id}",
        evidence_refs=list(approval.evidence),
    )
    outcome: ActionOutcome = svc.execute(action, approval=approval, actor_id=str(reviewer.id))
    approval.executed_at = datetime.now(UTC)
    approval.tool_execution_id = uuid.UUID(outcome.tool_execution_id) if outcome.tool_execution_id else None
    approval.execution_result = outcome.model_dump(mode="json", exclude={"decision"})
    approval.status = "executed" if outcome.outcome in {"executed", "duplicate"} else "execution_failed"
    db.flush()
    db.commit()
    _resume_workflow(db, approval)
    return {"approval_id": str(approval.id), "status": approval.status, "execution": approval.execution_result}


def _resume_workflow(db: Session, approval: Approval) -> None:
    if not approval.run_id:
        return
    from app.orchestration.engine import resume_after_approval

    resume_after_approval(db, run_id=str(approval.run_id), approval=approval)
