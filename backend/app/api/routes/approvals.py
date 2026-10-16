"""Approval center."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.schemas import ApprovalDecisionIn, ApprovalOut, Page
from app.api.serializers import approval_out
from app.core.errors import AuthorizationError, NotFound
from app.db.models import Approval, User
from app.db.session import get_db
from app.services.approvals import decide_approval, expire_stale_approvals

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _names(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return {u.id: u.full_name for u in db.execute(select(User).where(User.id.in_(ids))).scalars().all()}


@router.get("", response_model=Page[ApprovalOut], summary="List approvals")
def list_approvals(
    status: str | None = Query(default="pending"),
    risk_level: str | None = None,
    agent_key: str | None = None,
    run_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require("approvals:read")),
    db: Session = Depends(get_db),
) -> Page[ApprovalOut]:
    expire_stale_approvals(db, principal.tenant.id)
    db.commit()
    stmt = select(Approval).where(Approval.tenant_id == principal.tenant.id)
    if status and status != "all":
        stmt = stmt.where(Approval.status.in_(status.split(",")))
    if risk_level:
        stmt = stmt.where(Approval.risk_level == risk_level)
    if agent_key:
        stmt = stmt.where(Approval.agent_key == agent_key)
    if run_id:
        stmt = stmt.where(Approval.run_id == uuid.UUID(run_id))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Approval.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    names = _names(db, {r.reviewer_id for r in rows if r.reviewer_id})
    return Page(items=[approval_out(a, names.get(a.reviewer_id) if a.reviewer_id else None) for a in rows], total=total, limit=limit, offset=offset)


@router.get("/{approval_id}", response_model=ApprovalOut, summary="Approval detail")
def get_approval(approval_id: str, principal: Principal = Depends(require("approvals:read")), db: Session = Depends(get_db)) -> ApprovalOut:
    a = db.get(Approval, uuid.UUID(approval_id))
    if a is None or a.tenant_id != principal.tenant.id:
        raise NotFound("Approval not found")
    names = _names(db, {a.reviewer_id} if a.reviewer_id else set())
    return approval_out(a, names.get(a.reviewer_id) if a.reviewer_id else None)


@router.post("/{approval_id}/decision", summary="Approve or reject a pending action (executes exactly once on approval)")
def decide(approval_id: str, body: ApprovalDecisionIn, principal: Principal = Depends(require("approvals:decide")), db: Session = Depends(get_db)) -> dict:
    if principal.user is None:
        raise AuthorizationError("Approvals must be decided by a human user, not an API key")
    result = decide_approval(
        db, tenant=principal.tenant, approval_id=approval_id, reviewer=principal.user, reviewer_permissions=principal.permissions,
        decision=body.decision, note=body.note, payload_hash_check=body.payload_hash,
    )
    a = db.get(Approval, uuid.UUID(approval_id))
    assert a is not None
    db.refresh(a)
    return {**result, "approval": approval_out(a, principal.user.full_name).model_dump(mode="json")}
