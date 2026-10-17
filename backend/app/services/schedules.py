"""Scheduled workflows (definition trigger {"schedule": "hourly" | "daily" | "weekly"}).

Opt-in per workspace (tenant.settings["schedules"][workflow_key] = true) so a schedule never
spends AI quota nobody asked for. Called from the 60 s maintenance loop on every API/worker
instance: each period starts at most one run per workspace, guaranteed by the run's idempotency
key ("schedule:<key>:<period>") and the unique (tenant_id, idempotency_key) constraint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import OpsPilotError
from app.core.logging import get_logger
from app.db.models import Tenant, WorkflowDefinition, WorkflowRun

log = get_logger("schedules")

SCHEDULES = ("hourly", "daily", "weekly")
# Inputs for scheduled runs (the trigger has no payload).
SCHEDULE_INPUTS: dict[str, dict[str, Any]] = {"kpi_report": {"period_days": 7, "months": 1}}


def period_key(schedule: str, now: datetime) -> str:
    if schedule == "hourly":
        return now.strftime("%Y%m%d%H")
    if schedule == "daily":
        return now.strftime("%Y%m%d")
    year, week, _ = now.isocalendar()
    return f"{year}W{week:02d}"


def schedulable(definition: WorkflowDefinition) -> str | None:
    schedule = (definition.trigger or {}).get("schedule")
    return schedule if schedule in SCHEDULES else None


def enabled_schedules(tenant: Tenant) -> dict[str, bool]:
    return {k: bool(v) for k, v in ((tenant.settings or {}).get("schedules") or {}).items()}


def run_due_schedules(db: Session, now: datetime | None = None) -> int:
    """Start this period's run for every enabled schedule that has none yet. Returns runs started."""
    from app.orchestration.engine import load_definition, start_run

    now = now or datetime.now(UTC)
    started = 0
    for tenant in db.execute(select(Tenant).where(Tenant.status == "active", Tenant.emergency_disabled.is_(False))).scalars().all():
        wanted = [k for k, on in enabled_schedules(tenant).items() if on]
        for key in wanted:
            try:
                definition = load_definition(db, tenant.id, key)
            except OpsPilotError:
                continue
            schedule = schedulable(definition)
            if schedule is None:
                continue
            idem = f"schedule:{key}:{period_key(schedule, now)}"
            if db.execute(select(WorkflowRun.id).where(WorkflowRun.tenant_id == tenant.id, WorkflowRun.idempotency_key == idem)).first():
                continue
            try:
                start_run(db, tenant_id=str(tenant.id), workflow_key=key, input=dict(SCHEDULE_INPUTS.get(key, {})), actor_id="scheduler", idempotency_key=idem)
                started += 1
                log.info("schedule.started", tenant=tenant.slug, workflow=key, period=idem)
            except IntegrityError:  # another instance started it first
                db.rollback()
            except OpsPilotError as exc:  # quota exhausted, tenant disabled, ...
                db.rollback()
                log.warning("schedule.skipped", tenant=tenant.slug, workflow=key, reason=exc.message)
    return started
