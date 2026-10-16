"""Durable, database-backed job queue.

Any number of worker processes (``python -m app.workers.runner``) - or the
in-process pool in ``thread`` mode - claim jobs concurrently:

* PostgreSQL: ``UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED)``
* SQLite / others: per-row conditional ``UPDATE ... WHERE status='queued'``
  (the row count tells exactly one worker that it won)

Each claimed job carries a lease that the worker renews while it runs. If a
worker dies, the lease expires and the reaper puts the job back in the queue
(or marks it ``dead`` after ``max_attempts``). Tenants are capped at their
``max_concurrent_runs`` quota so one tenant cannot starve the others.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import Job, Tenant

log = get_logger("jobs")
DEFAULT_LEASE_SECONDS = 120

Handler = Callable[[dict[str, Any], str], Any]
_HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _HANDLERS[kind] = fn
        return fn

    return deco


def get_handler(kind: str) -> Handler:
    _load_builtin_handlers()
    return _HANDLERS[kind]


DeadHook = Callable[[Session, Job], None]
_DEAD_HOOKS: dict[str, DeadHook] = {}


def on_dead(kind: str) -> Callable[[DeadHook], DeadHook]:
    """Register what to do with the owning record when a job of this kind goes to `dead`."""

    def deco(fn: DeadHook) -> DeadHook:
        _DEAD_HOOKS[kind] = fn
        return fn

    return deco


def _notify_dead(db: Session, job: Job) -> None:
    _load_builtin_handlers()
    hook = _DEAD_HOOKS.get(job.kind)
    if hook is None:
        return
    try:
        hook(db, job)
        db.commit()
    except Exception:  # noqa: BLE001 - the job is already dead; never let the hook break the worker
        db.rollback()
        log.exception("job.dead_hook_failed", job=str(job.id), kind=job.kind)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Producer side
# ---------------------------------------------------------------------------


def enqueue_job(
    db: Session,
    *,
    kind: str,
    payload: dict[str, Any],
    tenant_id: str | uuid.UUID | None = None,
    delay_seconds: float = 0.0,
    priority: int = 100,
    dedupe_key: str | None = None,
    max_attempts: int = 5,
    coalesce_on: str | None = None,
) -> Job | None:
    """Insert a job. ``dedupe_key`` is globally unique (idempotent enqueue);
    ``coalesce_on`` skips the insert while an identical queued/running job exists."""
    if dedupe_key:
        existing = db.execute(select(Job).where(Job.dedupe_key == dedupe_key)).scalar_one_or_none()
        if existing:
            return existing
    if coalesce_on:
        open_jobs = db.execute(select(Job).where(Job.kind == kind, Job.status.in_(["queued", "running"]))).scalars().all()
        for j in open_jobs:
            if (j.payload or {}).get(coalesce_on) == payload.get(coalesce_on):
                if j.status == "queued" and delay_seconds == 0 and j.run_at and _aware(j.run_at) > _now():
                    j.run_at = _now()
                return None
    job = Job(
        tenant_id=uuid.UUID(str(tenant_id)) if tenant_id else None,
        kind=kind,
        payload=payload,
        priority=priority,
        run_at=_now() + timedelta(seconds=delay_seconds),
        dedupe_key=dedupe_key,
        max_attempts=max_attempts,
    )
    db.add(job)
    db.flush()
    return job


# ---------------------------------------------------------------------------
# Consumer side
# ---------------------------------------------------------------------------


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _tenant_capacity(db: Session, tenant_ids: set[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Remaining concurrent-job slots per tenant (quota max_concurrent_runs minus running jobs)."""
    if not tenant_ids:
        return {}
    running = dict(db.execute(select(Job.tenant_id, func.count()).where(Job.status == "running", Job.tenant_id.in_(tenant_ids)).group_by(Job.tenant_id)).all())
    caps = {t.id: int((t.quotas or {}).get("max_concurrent_runs", 25)) for t in db.execute(select(Tenant).where(Tenant.id.in_(tenant_ids))).scalars().all()}
    return {tid: caps.get(tid, 25) - running.get(tid, 0) for tid in tenant_ids}


def claim_jobs(db: Session, worker: str, limit: int, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> list[Job]:
    """Atomically claim up to `limit` ready jobs, never exceeding any tenant's concurrency cap."""
    if limit <= 0:
        return []
    now = _now()
    lease = now + timedelta(seconds=lease_seconds)
    is_pg = db.bind is not None and db.bind.dialect.name == "postgresql"
    stmt = select(Job.id, Job.tenant_id).where(Job.status == "queued", Job.run_at <= now).order_by(Job.priority, Job.run_at).limit(limit * 4)
    if is_pg:
        stmt = stmt.with_for_update(skip_locked=True)  # concurrent workers see disjoint candidate sets
    candidates = db.execute(stmt).all()
    remaining = _tenant_capacity(db, {tid for _, tid in candidates if tid is not None})
    ids: list[uuid.UUID] = []
    for jid, tid in candidates:
        if tid is not None and remaining.get(tid, 0) <= 0:
            continue
        res = db.execute(
            update(Job)
            .execution_options(synchronize_session=False)
            .where(Job.id == jid, Job.status == "queued")
            .values(status="running", locked_by=worker, lease_until=lease, attempts=Job.attempts + 1, started_at=now, updated_at=now)
        )
        if res.rowcount == 1:  # exactly one worker wins each row
            ids.append(jid)
            if tid is not None:
                remaining[tid] -= 1
        if len(ids) >= limit:
            break
    db.commit()
    if not ids:
        return []
    return list(db.execute(select(Job).where(Job.id.in_(ids)).execution_options(populate_existing=True)).scalars().all())


def renew_leases(db: Session, worker: str, job_ids: list[uuid.UUID], lease_seconds: int = DEFAULT_LEASE_SECONDS) -> int:
    if not job_ids:
        return 0
    res = db.execute(update(Job).execution_options(synchronize_session=False).where(Job.id.in_(job_ids), Job.locked_by == worker, Job.status == "running").values(lease_until=_now() + timedelta(seconds=lease_seconds)))
    db.commit()
    return res.rowcount or 0


def complete_job(db: Session, job_id: uuid.UUID, worker: str, result: Any = None) -> None:
    db.execute(
        update(Job).execution_options(synchronize_session=False)
        .where(Job.id == job_id, Job.locked_by == worker)
        .values(status="done", finished_at=_now(), lease_until=None, result=result if isinstance(result, dict) else ({"value": result} if result is not None else None))
    )
    db.commit()


def fail_job(db: Session, job_id: uuid.UUID, worker: str, error: str) -> str:
    job = db.get(Job, job_id, populate_existing=True)
    if job is None or job.locked_by != worker:
        return "lost"
    job.last_error = error[:4000]
    job.lease_until = None
    if job.attempts >= job.max_attempts:
        job.status = "dead"
        job.finished_at = _now()
    else:
        job.status = "queued"
        backoff = min(300.0, (2 ** job.attempts) * 2.0) * (1 + random.uniform(0, 0.25))  # noqa: S311 - jitter, not crypto
        job.run_at = _now() + timedelta(seconds=backoff)
    db.commit()
    if job.status == "dead":
        _notify_dead(db, job)
    return job.status


def reap_expired_leases(db: Session) -> dict[str, int]:
    """Return jobs whose worker vanished to the queue (or to `dead`)."""
    now = _now()
    requeued = dead = 0
    died: list[Job] = []
    for job in db.execute(select(Job).where(Job.status == "running", Job.lease_until.isnot(None), Job.lease_until < now).execution_options(populate_existing=True)).scalars().all():
        job.locked_by = None
        job.lease_until = None
        job.last_error = (job.last_error or "") + f"\nlease expired at {now.isoformat()} (worker lost)"
        if job.attempts >= job.max_attempts:
            job.status = "dead"
            job.finished_at = now
            dead += 1
            died.append(job)
        else:
            job.status = "queued"
            job.run_at = now
            requeued += 1
    db.commit()
    for job in died:
        _notify_dead(db, job)
    if requeued or dead:
        log.warning("jobs.reaped", requeued=requeued, dead=dead)
    return {"requeued": requeued, "dead": dead}


def retry_dead_job(db: Session, job_id: uuid.UUID) -> Job | None:
    job = db.get(Job, job_id, populate_existing=True)
    if job is None or job.status not in {"dead", "failed"}:
        return None
    job.status = "queued"
    job.attempts = 0
    job.run_at = _now()
    job.last_error = None
    job.finished_at = None
    db.commit()
    return job


def queue_stats(db: Session, tenant_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Queue depth; with tenant_id only that tenant's jobs are counted (what a tenant may see)."""
    if tenant_id is not None:
        scope = Job.tenant_id == tenant_id
        by_status = dict(db.execute(select(Job.status, func.count()).where(scope).group_by(Job.status)).all())
        by_kind = [{"kind": k, "status": s, "count": n} for k, s, n in db.execute(select(Job.kind, Job.status, func.count()).where(scope).group_by(Job.kind, Job.status)).all()]
        oldest = db.execute(select(func.min(Job.run_at)).where(scope, Job.status == "queued", Job.run_at <= _now())).scalar_one_or_none()
        lag = (_now() - _aware(oldest)).total_seconds() if oldest else 0.0
        return {"by_status": {k: by_status.get(k, 0) for k in ("queued", "running", "done", "failed", "dead")}, "by_kind": by_kind, "oldest_ready_lag_seconds": round(max(lag, 0.0), 2)}
    return _global_queue_stats(db)


def _global_queue_stats(db: Session) -> dict[str, Any]:
    by_status = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    by_kind = [{"kind": k, "status": s, "count": n} for k, s, n in db.execute(select(Job.kind, Job.status, func.count()).group_by(Job.kind, Job.status)).all()]
    oldest = db.execute(select(func.min(Job.run_at)).where(Job.status == "queued", Job.run_at <= _now())).scalar_one_or_none()
    lag = (_now() - _aware(oldest)).total_seconds() if oldest else 0.0
    return {"by_status": {k: by_status.get(k, 0) for k in ("queued", "running", "done", "failed", "dead")}, "by_kind": by_kind, "oldest_ready_lag_seconds": round(max(lag, 0.0), 2)}


# ---------------------------------------------------------------------------
# Built-in handlers
# ---------------------------------------------------------------------------

_loaded = False


def _load_builtin_handlers() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True

    @handler("workflow.execute")
    def _workflow(payload: dict[str, Any], worker: str) -> Any:
        from app.orchestration.engine import execute_run

        return execute_run(payload["run_id"], worker_id=worker)

    @handler("copilot.turn")
    def _copilot(payload: dict[str, Any], worker: str) -> Any:
        from app.copilot.service import process_turn

        return process_turn(payload["message_id"])

    @handler("batch.item")
    def _batch(payload: dict[str, Any], worker: str) -> Any:
        from app.services.batches import process_batch_item

        return process_batch_item(payload["item_id"])

    @handler("maintenance")
    def _maint(payload: dict[str, Any], worker: str) -> Any:
        from app.workers.queue import run_scheduled_maintenance

        return run_scheduled_maintenance()

    # When a job gives up, the record waiting on it must not wait forever.
    @on_dead("batch.item")
    def _batch_dead(db: Session, job: Job) -> None:
        from app.services.batches import fail_item_permanently

        fail_item_permanently(db, (job.payload or {})["item_id"], job.last_error or "job exhausted its attempts")

    @on_dead("copilot.turn")
    def _copilot_dead(db: Session, job: Job) -> None:
        from app.copilot.service import fail_turn

        fail_turn(db, (job.payload or {})["message_id"], job.last_error or "job exhausted its attempts")
