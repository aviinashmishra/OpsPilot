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
    assert set(out) == {"approvals_expired", "jobs_requeued", "runs_recovered", "executions_reconciled", "metrics_rows", "purged", "audit_sealed"}
    assert apply_retention(db) >= 0
