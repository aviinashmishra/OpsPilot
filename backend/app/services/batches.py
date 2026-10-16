"""Bulk agent runs: fan one agent out over thousands of inputs through the job queue.

Each item is an independent job, so throughput scales with worker processes;
counters are updated with atomic SQL increments so parallel workers never lose
an update, and the batch completes exactly once.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from app.agents.registry import agent_registry
from app.core.config import get_settings
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db.models import AgentBatch, AgentBatchItem, Job, Tenant, User
from app.db.session import session_scope
from app.services.audit import record_audit

MAX_ITEMS = 5000


def create_batch(db: Session, *, tenant: Tenant, agent_key: str, items: list[dict[str, Any]], actor_id: str, name: str | None = None, execute_actions: bool = True) -> AgentBatch:
    if not agent_registry.has(agent_key):
        raise NotFound(f"Agent '{agent_key}' not found")
    if not items:
        raise ValidationFailed("Provide at least one item")
    if len(items) > MAX_ITEMS:
        raise ValidationFailed(f"At most {MAX_ITEMS} items per batch")
    agent = agent_registry.get(agent_key)
    errors = []
    for i, item in enumerate(items[:MAX_ITEMS]):
        try:
            agent.validate_input(item)
        except Exception as exc:  # noqa: BLE001
            errors.append({"index": i, "error": str(exc).split("\n")[0][:300]})
        if len(errors) >= 20:
            break
    if errors:
        raise ValidationFailed(f"{len(errors)} item(s) do not match the agent's input schema", details={"errors": errors})
    batch = AgentBatch(tenant_id=tenant.id, agent_key=agent_key, name=name or f"{agent.spec.name} × {len(items)}", total=len(items), execute_actions=execute_actions, created_by=actor_id, correlation_id=uuid.uuid4().hex)
    db.add(batch)
    db.flush()
    rows = [AgentBatchItem(tenant_id=tenant.id, batch_id=batch.id, item_index=i, input=item) for i, item in enumerate(items)]
    db.add_all(rows)
    db.flush()
    record_audit(db, tenant_id=tenant.id, action="batch.created", resource_type="agent_batch", resource_id=str(batch.id), actor_id=actor_id, details={"agent": agent_key, "items": len(items), "execute_actions": execute_actions}, correlation_id=batch.correlation_id)
    db.commit()
    from app.workers.queue import dispatch

    for row in rows:
        dispatch("batch.item", {"item_id": str(row.id)}, tenant_id=str(tenant.id), priority=150, dedupe_key=f"batch-item:{row.id}")
    return batch


def cancel_batch(db: Session, batch: AgentBatch) -> AgentBatch:
    if batch.status != "running":
        raise Conflict(f"Batch is already {batch.status}")
    batch.status = "cancelled"
    batch.finished_at = datetime.now(UTC)
    item_ids = [str(i) for i in db.execute(select(AgentBatchItem.id).where(AgentBatchItem.batch_id == batch.id, AgentBatchItem.status == "queued")).scalars().all()]
    db.execute(update(AgentBatchItem).execution_options(synchronize_session=False).where(AgentBatchItem.batch_id == batch.id, AgentBatchItem.status == "queued").values(status="cancelled"))
    if item_ids:
        db.execute(update(Job).execution_options(synchronize_session=False).where(Job.kind == "batch.item", Job.status == "queued", Job.dedupe_key.in_([f"batch-item:{i}" for i in item_ids])).values(status="done", finished_at=datetime.now(UTC), result={"cancelled": True}))
    db.commit()
    return batch


def fail_item_permanently(db: Session, item_id: str, error: str) -> None:
    """The item's job is dead: count the item as failed so the batch can still complete."""
    item = db.get(AgentBatchItem, uuid.UUID(item_id))
    if item is None:
        return
    moved = db.execute(
        update(AgentBatchItem).execution_options(synchronize_session=False)
        .where(AgentBatchItem.id == item.id, AgentBatchItem.status.in_(["queued", "running"]))
        .values(status="failed", error=error[:1000], updated_at=datetime.now(UTC))
    )
    if (moved.rowcount or 0) == 1:
        _count_and_maybe_complete(db, item.batch_id, AgentBatch.failed, 0.0)


def _count_and_maybe_complete(db: Session, batch_id: uuid.UUID, counter: Any, cost: float) -> None:
    db.execute(update(AgentBatch).execution_options(synchronize_session=False).where(AgentBatch.id == batch_id).values({counter.key: counter + 1, "cost_usd": AgentBatch.cost_usd + cost}))
    db.execute(
        update(AgentBatch)
        .execution_options(synchronize_session=False)
        .where(AgentBatch.id == batch_id, AgentBatch.status == "running", (AgentBatch.succeeded + AgentBatch.failed + AgentBatch.needs_review) >= AgentBatch.total)
        .values(status="completed", finished_at=datetime.now(UTC))
    )


def _is_transient_db_error(exc: BaseException) -> bool:
    seen: BaseException | None = exc
    for _ in range(6):  # agents wrap errors; walk the cause chain
        if seen is None:
            return False
        if isinstance(seen, DBAPIError) and (isinstance(seen, OperationalError) or seen.connection_invalidated):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def process_batch_item(item_id: str) -> dict[str, Any]:
    from app.agents.runner import run_agent

    with session_scope() as db:
        item = db.get(AgentBatchItem, uuid.UUID(item_id))
        if item is None:
            return {"status": "missing"}
        batch = db.get(AgentBatch, item.batch_id)
        if batch is None or batch.status == "cancelled" or item.status not in {"queued", "running"}:
            return {"status": item.status}
        # Claim the item. A "running" item whose worker died (its job lease expired and the job was
        # re-queued) is reclaimable once stale; side effects stay deduplicated by idempotency keys.
        stale_before = datetime.now(UTC) - timedelta(seconds=get_settings().batch_item_stale_seconds)
        claim_token = datetime.now(UTC)  # updated_at doubles as the claim token: a later reclaim changes it
        claimed = db.execute(
            update(AgentBatchItem)
            .execution_options(synchronize_session=False)
            .where(AgentBatchItem.id == item.id, or_(AgentBatchItem.status == "queued", and_(AgentBatchItem.status == "running", AgentBatchItem.updated_at < stale_before)))
            .values(status="running", updated_at=claim_token)
        )
        db.commit()
        if (claimed.rowcount or 0) != 1:
            return {"status": "already_processing"}
        tenant = db.get(Tenant, batch.tenant_id)
        assert tenant is not None
        perms = ["*"]
        actor = batch.created_by or "system"
        try:
            user = db.get(User, uuid.UUID(actor)) if actor and actor not in {"system"} and not actor.startswith("apikey:") else None
        except ValueError:
            user = None
        if user is not None:
            perms = sorted({p for r in user.roles for p in (r.permissions or [])})
        started = time.perf_counter()
        status, summary, error, approvals, run_id, cost = "completed", None, None, [], None, 0.0
        try:
            out = run_agent(
                db, tenant=tenant, agent_key=batch.agent_key, input=item.input, actor_id=actor, permissions=perms, correlation_id=batch.correlation_id,
                execute_actions=batch.execute_actions, extra_context={"batch_id": str(batch.id)}, idempotency_scope=f"batch-item:{item.id}",
            )
            summary = out.result.summary
            approvals = [a.approval_id for a in out.actions if a.approval_id]
            run_id = uuid.UUID(out.agent_run_id)
            cost = float(out.usage.get("cost_usd", 0.0))
            if approvals or out.status in {"needs_input", "escalated", "needs_approval"}:
                status = "needs_review"
        except Exception as exc:  # noqa: BLE001 - one bad item never stops the batch
            db.rollback()
            if _is_transient_db_error(exc):
                # Database busy / connection dropped: not the item's fault. Put it back and let the job
                # queue retry it with backoff (its actions are idempotent per item, so nothing doubles).
                db.execute(update(AgentBatchItem).execution_options(synchronize_session=False).where(AgentBatchItem.id == item.id, AgentBatchItem.updated_at == claim_token).values(status="queued"))
                db.commit()
                raise
            status, error = "failed", (getattr(exc, "message", None) or str(exc))[:1000]
        counter = {"completed": AgentBatch.succeeded, "needs_review": AgentBatch.needs_review, "failed": AgentBatch.failed}[status]
        recorded = db.execute(
            update(AgentBatchItem).execution_options(synchronize_session=False)
            .where(AgentBatchItem.id == item.id, AgentBatchItem.status == "running", AgentBatchItem.updated_at == claim_token)
            .values(status=status, summary=summary, error=error, approval_ids=approvals, agent_run_id=run_id, latency_ms=int((time.perf_counter() - started) * 1000))
        )
        if (recorded.rowcount or 0) != 1:
            # Someone reclaimed this item while we were slow; their result is the one that counts.
            db.commit()
            return {"status": "superseded"}
        _count_and_maybe_complete(db, batch.id, counter, cost)
        db.commit()
        return {"status": status}
