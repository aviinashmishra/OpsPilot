"""Horizontal-scale guarantees: concurrent job claiming, leases, retries, run locks."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import Job, WorkflowRun
from app.db.session import get_sessionmaker
from app.orchestration import engine
from app.workers import jobs as jq


def _clear(db):
    db.query(Job).delete()
    db.commit()


def test_many_workers_claim_each_job_exactly_once(db, demo_tenant):
    _clear(db)
    for i in range(60):
        jq.enqueue_job(db, kind="noop", payload={"i": i}, tenant_id=demo_tenant.id)
    db.commit()
    claimed: dict[str, list[int]] = {}
    errors: list[str] = []

    def worker(name: str) -> None:
        s = get_sessionmaker()()
        try:
            while True:
                got = jq.claim_jobs(s, name, 4)
                if not got:
                    break
                claimed.setdefault(name, []).extend(j.payload["i"] for j in got)
                for j in got:  # finish work like a real worker so the tenant cap frees up
                    jq.complete_job(s, j.id, name)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
        finally:
            s.close()

    threads = [threading.Thread(target=worker, args=(f"w{n}",)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    all_ids = [i for ids in claimed.values() for i in ids]
    assert not errors
    assert sorted(all_ids) == list(range(60)), "every job claimed exactly once across workers"
    assert len(claimed) >= 2, "work was shared between workers"


def test_tenant_concurrency_cap(db, demo_tenant):
    _clear(db)
    demo_tenant.quotas = {**(demo_tenant.quotas or {}), "max_concurrent_runs": 2}
    db.commit()
    for i in range(5):
        jq.enqueue_job(db, kind="noop", payload={"i": i}, tenant_id=demo_tenant.id)
    db.commit()
    first = jq.claim_jobs(db, "w1", 10)
    assert len(first) == 2 and jq.claim_jobs(db, "w2", 10) == []
    jq.complete_job(db, first[0].id, "w1")
    assert len(jq.claim_jobs(db, "w2", 10)) == 1
    demo_tenant.quotas = {**demo_tenant.quotas, "max_concurrent_runs": 25}
    db.commit()


def test_lease_expiry_requeues_then_dead_letters(db, demo_tenant):
    _clear(db)
    job = jq.enqueue_job(db, kind="noop", payload={}, tenant_id=demo_tenant.id, max_attempts=2)
    db.commit()
    jq.claim_jobs(db, "crashy", 1, lease_seconds=1)
    db.execute(Job.__table__.update().where(Job.id == job.id).values(lease_until=datetime.now(UTC) - timedelta(seconds=5)))
    db.commit()
    assert jq.reap_expired_leases(db) == {"requeued": 1, "dead": 0}
    jq.claim_jobs(db, "crashy", 1, lease_seconds=1)
    db.execute(Job.__table__.update().where(Job.id == job.id).values(lease_until=datetime.now(UTC) - timedelta(seconds=5)))
    db.commit()
    assert jq.reap_expired_leases(db) == {"requeued": 0, "dead": 1}
    assert jq.retry_dead_job(db, job.id).status == "queued"


def test_failures_back_off_and_dedupe(db, demo_tenant):
    _clear(db)
    a = jq.enqueue_job(db, kind="noop", payload={}, dedupe_key="once")
    b = jq.enqueue_job(db, kind="noop", payload={}, dedupe_key="once")
    db.commit()
    assert a.id == b.id
    jq.claim_jobs(db, "w", 1)
    assert jq.fail_job(db, a.id, "w", "boom") == "queued"
    db.refresh(a)
    assert a.run_at.replace(tzinfo=UTC) > datetime.now(UTC) and jq.claim_jobs(db, "w", 1) == []
    assert jq.fail_job(db, a.id, "someone-else", "x") == "lost"
    assert jq.enqueue_job(db, kind="workflow.execute", payload={"run_id": "r1"}, coalesce_on="run_id") is not None
    db.commit()
    assert jq.enqueue_job(db, kind="workflow.execute", payload={"run_id": "r1"}, coalesce_on="run_id") is None


def test_run_lease_blocks_a_second_executor(db, demo_tenant):
    run = engine.start_run(db, tenant_id=str(demo_tenant.id), workflow_key="kpi_report", input={"period_days": 7}, actor_id="system", enqueue=False)
    assert engine._acquire_run_lease(db, run.id, "worker-a:1")
    out = engine.execute_run(str(run.id), worker_id="worker-b")
    assert out["status"] == "locked"
    db.refresh(run)
    assert run.status == "pending" and run.step_count == 0
    engine._release_run_lease(db, run.id, "worker-a:1")
    assert engine.execute_run(str(run.id), worker_id="worker-b")["status"] in {"completed", "waiting_approval"}
    db.refresh(run)
    assert run.lease_owner is None


def test_worker_pool_drains_queue(db, demo_tenant):
    """A real WorkerPool (threads + leases + heartbeats) executes queued workflow jobs."""
    from app.db.models import WorkerHeartbeat
    from app.workers.pool import WorkerPool

    _clear(db)
    runs = [engine.start_run(db, tenant_id=str(demo_tenant.id), workflow_key="kpi_report", input={"period_days": 7, "months": 2}, actor_id="system", enqueue=False) for _ in range(4)]
    for r in runs:
        jq.enqueue_job(db, kind="workflow.execute", payload={"run_id": str(r.id)}, tenant_id=demo_tenant.id)
    db.commit()
    pool = WorkerPool(name=f"test-{uuid.uuid4().hex[:6]}", concurrency=3, poll_interval=0.05).start()
    try:
        import time

        deadline = time.time() + 60
        while time.time() < deadline:
            db.expire_all()
            if all(db.get(WorkflowRun, r.id).status in {"completed", "waiting_approval"} for r in runs):
                break
            time.sleep(0.2)
    finally:
        pool.stop()
    db.expire_all()
    assert all(db.get(WorkflowRun, r.id).status in {"completed", "waiting_approval"} for r in runs)
    assert db.execute(select(Job).where(Job.status != "done")).first() is None
    hb = db.execute(select(WorkerHeartbeat).where(WorkerHeartbeat.name == pool.name)).scalar_one()
    assert hb.processed == 4 and hb.status == "stopped"


def test_system_queue_endpoint(client, admin_headers):
    r = client.get("/api/v1/system/queue", headers=admin_headers)
    assert r.status_code == 200 and set(r.json()["by_status"]) == {"queued", "running", "done", "failed", "dead"}
