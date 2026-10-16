"""Celery application (production worker mode). Requires REDIS_URL."""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init

from app.core.config import get_settings

settings = get_settings()
broker = settings.redis_url or "memory://"

celery_app = Celery("opspilot", broker=broker, backend=settings.redis_url or None)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,  # a crashed worker leaves the task to be redelivered; state is in the DB
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_time_limit=settings.workflow_default_timeout_seconds + 60,
    task_default_queue="workflows",
    task_routes={"app.workers.celery_app.execute_run_task": {"queue": "workflows"}},
    beat_schedule={
        "maintenance-every-minute": {"task": "app.workers.celery_app.maintenance_task", "schedule": 60.0},
    },
)


@worker_process_init.connect
def _drain_db_queue(**_: object) -> None:
    """Workflows arrive through Redis; Copilot turns, bulk-run items and other jobs live in the
    durable DB queue. Every Celery worker process also drains that queue, so celery mode needs
    no extra service."""
    import app.tools.catalog  # noqa: F401 - registers tools
    from app.agents.registry import agent_registry
    from app.workers.pool import start_local_pool

    agent_registry.load_builtin()
    start_local_pool(max(1, settings.worker_concurrency // 2))


@celery_app.task(name="app.workers.celery_app.execute_run_task", bind=True, max_retries=0)
def execute_run_task(self, run_id: str) -> dict:  # type: ignore[no-untyped-def]
    from app.orchestration.engine import execute_run

    return execute_run(run_id, worker_id=f"celery-{self.request.hostname}")


@celery_app.task(name="app.workers.celery_app.maintenance_task")
def maintenance_task() -> dict:
    from app.workers.queue import run_scheduled_maintenance

    return run_scheduled_maintenance()
