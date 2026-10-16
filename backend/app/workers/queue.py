"""Background execution entry points.

WORKER_MODE
  inline : execute synchronously in the caller (tests, scripts)
  thread : durable DB job queue drained by an in-process worker pool (local dev, single node)
  db     : durable DB job queue drained by separate ``python -m app.workers.runner`` processes
           (horizontal scale without Redis: add processes/machines)
  celery : Celery + Redis

Workflow state, checkpoints and run leases live in the database in every mode,
so a crash never loses progress and two workers can never execute one run at once.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("queue")


def dispatch(kind: str, payload: dict[str, Any], *, tenant_id: str | None = None, delay_seconds: float = 0.0, priority: int = 100, dedupe_key: str | None = None, coalesce_on: str | None = None) -> None:
    """Run a background job according to WORKER_MODE."""
    mode = get_settings().worker_mode
    if mode == "inline":
        from app.workers.jobs import get_handler

        if delay_seconds:
            time.sleep(min(delay_seconds, 2))
        get_handler(kind)(payload, "inline")
        return
    if mode == "celery" and kind == "workflow.execute":
        from app.workers.celery_app import execute_run_task

        execute_run_task.apply_async(args=[payload["run_id"]], countdown=delay_seconds or None)
        return
    from app.db.session import session_scope
    from app.workers.jobs import enqueue_job

    with session_scope(tenant_id) as db:
        enqueue_job(db, kind=kind, payload=payload, tenant_id=tenant_id, delay_seconds=delay_seconds, priority=priority, dedupe_key=dedupe_key, coalesce_on=coalesce_on)
    from app.workers.pool import get_local_pool

    pool = get_local_pool()
    if pool is not None:
        pool.wake()


def enqueue_run(run_id: str, delay_seconds: float = 0.0) -> None:
    dispatch("workflow.execute", {"run_id": run_id}, delay_seconds=delay_seconds, priority=50, coalesce_on="run_id")


def wait_for_idle(timeout: float = 30.0) -> bool:
    """Block until queued/running jobs drain (tests and scripts)."""
    from sqlalchemy import func, select

    from app.db.models import Job
    from app.db.session import get_sessionmaker

    deadline = time.time() + timeout
    while time.time() < deadline:
        with get_sessionmaker()() as db:
            open_jobs = db.execute(select(func.count()).select_from(Job).where(Job.status.in_(["queued", "running"]))).scalar_one()
        if open_jobs == 0:
            return True
        time.sleep(0.1)
    return False


def run_scheduled_maintenance() -> dict[str, int]:
    """Periodic housekeeping callable from Celery beat or a local scheduler thread."""
    from app.db.session import session_scope
    from app.orchestration.engine import recover_stale_runs
    from app.services.approvals import expire_stale_approvals
    from app.services.audit import seal_all
    from app.services.maintenance import apply_retention, compute_daily_metrics, reconcile_unknown_executions
    from app.workers.jobs import reap_expired_leases

    with session_scope() as db:
        expired = expire_stale_approvals(db)
        reaped = reap_expired_leases(db)
        recovered = recover_stale_runs(db)
        reconciled = reconcile_unknown_executions(db)
        metrics = compute_daily_metrics(db)
        purged = apply_retention(db)
    with session_scope() as db:  # its own short transaction: sealing takes a per-tenant lock
        sealed = seal_all(db)
    return {"approvals_expired": expired, "jobs_requeued": reaped["requeued"], "runs_recovered": len(recovered), "executions_reconciled": reconciled, "metrics_rows": metrics, "purged": purged, "audit_sealed": sealed}


_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()


def start_local_scheduler(interval_seconds: int = 60) -> None:
    """Lightweight in-process scheduler (Celery beat or cron replaces this in production)."""
    global _scheduler_thread
    if _scheduler_thread is not None:
        return

    def _loop() -> None:
        while not _scheduler_stop.wait(interval_seconds):
            try:
                run_scheduled_maintenance()
            except Exception:  # noqa: BLE001
                log.exception("scheduler.maintenance_failed")

    _scheduler_thread = threading.Thread(target=_loop, name="opspilot-scheduler", daemon=True)
    _scheduler_thread.start()


def stop_local_scheduler() -> None:
    _scheduler_stop.set()
