"""Usage metering and tenant quotas."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import QuotaExceeded
from app.db.models import Tenant, UsageRecord


def current_period(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m")


def record_usage(
    db: Session,
    *,
    tenant_id: str | uuid.UUID,
    kind: str,
    quantity: float,
    cost_usd: float = 0.0,
    agent_key: str | None = None,
    run_id: str | uuid.UUID | None = None,
    model: str | None = None,
    meta: dict[str, Any] | None = None,
) -> UsageRecord:
    rec = UsageRecord(
        tenant_id=uuid.UUID(str(tenant_id)),
        period=current_period(),
        kind=kind,
        quantity=quantity,
        cost_usd=cost_usd,
        agent_key=agent_key,
        run_id=uuid.UUID(str(run_id)) if run_id else None,
        model=model,
        meta=meta or {},
    )
    db.add(rec)
    db.flush()
    return rec


def period_totals(db: Session, tenant_id: str | uuid.UUID, period: str | None = None) -> dict[str, Any]:
    tid = uuid.UUID(str(tenant_id))
    p = period or current_period()
    rows = db.execute(
        select(UsageRecord.kind, func.sum(UsageRecord.quantity), func.sum(UsageRecord.cost_usd))
        .where(UsageRecord.tenant_id == tid, UsageRecord.period == p)
        .group_by(UsageRecord.kind)
    ).all()
    totals = {kind: {"quantity": float(q or 0), "cost_usd": float(c or 0)} for kind, q, c in rows}
    totals.setdefault("workflow_run", {"quantity": 0.0, "cost_usd": 0.0})
    totals.setdefault("llm_tokens", {"quantity": 0.0, "cost_usd": 0.0})
    totals.setdefault("tool_call", {"quantity": 0.0, "cost_usd": 0.0})
    totals.setdefault("agent_run", {"quantity": 0.0, "cost_usd": 0.0})
    return {"period": p, "totals": totals, "total_cost_usd": round(sum(v["cost_usd"] for v in totals.values()), 6)}


def tenant_quotas(tenant: Tenant) -> dict[str, int]:
    s = get_settings()
    q = dict(tenant.quotas or {})
    return {
        "monthly_workflow_runs": int(q.get("monthly_workflow_runs", s.default_monthly_workflow_quota)),
        "monthly_llm_tokens": int(q.get("monthly_llm_tokens", s.default_monthly_token_quota)),
        "max_concurrent_runs": int(q.get("max_concurrent_runs", 25)),
    }


def enforce_workflow_quota(db: Session, tenant: Tenant) -> None:
    quotas = tenant_quotas(tenant)
    totals = period_totals(db, tenant.id)
    used = totals["totals"]["workflow_run"]["quantity"]
    if used >= quotas["monthly_workflow_runs"]:
        raise QuotaExceeded("Monthly workflow quota exhausted", details={"used": used, "quota": quotas["monthly_workflow_runs"]})
    tokens = totals["totals"]["llm_tokens"]["quantity"]
    if tokens >= quotas["monthly_llm_tokens"]:
        raise QuotaExceeded("Monthly token quota exhausted", details={"used": tokens, "quota": quotas["monthly_llm_tokens"]})
