from app.services.maintenance import apply_retention, compute_daily_metrics
from app.workers.queue import run_scheduled_maintenance


def test_daily_metrics_computed(db, demo_tenant, client, operator_headers):
    client.post("/api/v1/agents/workflow_coordinator/run", json={"input": {}, "mode": "workflow"}, headers=operator_headers)
    n = compute_daily_metrics(db)
    db.commit()
    assert n >= 9
    from sqlalchemy import select

    from app.db.models import DailyMetric

    rows = db.execute(select(DailyMetric).where(DailyMetric.tenant_id == demo_tenant.id)).scalars().all()
    keys = {r.metric_key for r in rows}
    assert {"workflow_runs", "workflow_completion_rate", "ai_cost_usd", "cost_per_successful_workflow", "estimated_minutes_saved"} <= keys


def test_maintenance_job_runs(db):
    out = run_scheduled_maintenance()
    assert set(out) == {"approvals_expired", "jobs_requeued", "runs_recovered", "executions_reconciled", "metrics_rows", "purged", "audit_sealed", "scheduled_runs"}
    assert apply_retention(db) >= 0


def test_scheduled_workflows_are_opt_in_and_run_once_per_period(client, admin_headers, operator_headers, db, demo_tenant):
    from datetime import UTC, datetime

    from sqlalchemy import func, select

    from app.db.models import WorkflowRun
    from app.services.schedules import period_key, run_due_schedules

    defs = {d["key"]: d for d in client.get("/api/v1/workflows/definitions", headers=admin_headers).json()}
    assert defs["overdue_escalation"]["schedule_enabled"] is False and defs["lead_to_crm"]["schedule_enabled"] is None
    assert run_due_schedules(db) == 0  # off by default: no quota spent nobody asked for

    assert client.put("/api/v1/workflows/definitions/overdue_escalation/schedule", json={"enabled": True}, headers=operator_headers).status_code == 403
    assert client.put("/api/v1/workflows/definitions/lead_to_crm/schedule", json={"enabled": True}, headers=admin_headers).status_code == 422
    on = client.put("/api/v1/workflows/definitions/overdue_escalation/schedule", json={"enabled": True}, headers=admin_headers)
    assert on.status_code == 200 and on.json()["schedule_enabled"] is True
    db.expire_all()

    now = datetime(2026, 10, 17, 9, 30, tzinfo=UTC)
    assert period_key("hourly", now) == "2026101709" and period_key("weekly", now) == "2026W42"
    assert run_due_schedules(db, now) == 1
    assert run_due_schedules(db, now) == 0  # same hour: never twice (also across instances, via the unique key)
    assert run_due_schedules(db, now.replace(hour=10)) == 1
    idem = "schedule:overdue_escalation:2026101709"
    assert db.execute(select(func.count()).select_from(WorkflowRun).where(WorkflowRun.tenant_id == demo_tenant.id, WorkflowRun.idempotency_key == idem)).scalar_one() == 1
    client.put("/api/v1/workflows/definitions/overdue_escalation/schedule", json={"enabled": False}, headers=admin_headers)
    db.expire_all()
    assert run_due_schedules(db, now.replace(hour=11)) == 0
