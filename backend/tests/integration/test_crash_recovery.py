"""Crash recovery for queued work: re-run bulk items without duplicate side effects, interrupted
non-idempotent calls are verified instead of repeated, and dead jobs release the records waiting on them."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from app.agents.base import AgentContext, ProposedAction
from app.agents.registry import agent_registry
from app.db.models import AgentBatch, AgentBatchItem, CopilotMessage, Job, ToolExecution
from app.integrations import mock_adapters
from app.services.actions import ActionService
from app.services.batches import process_batch_item
from app.workers import jobs as jq
from tests.conftest import idem


def _lead(tag: str) -> dict:
    return {"lead": {"name": f"Crash {tag}", "email": f"crash-{tag}@example.test", "company": "Example", "title": "CEO", "company_size": 300, "budget": 40000, "timeline": "this quarter", "message": "We need to automate support."}}


def _side_effects(db, correlation_id: str) -> dict[str, int]:
    rows = db.execute(select(ToolExecution.tool_key, func.count()).where(ToolExecution.correlation_id == correlation_id, ToolExecution.side_effect.is_(True)).group_by(ToolExecution.tool_key)).all()
    return dict(rows)


def _make_stale(db, item_id: uuid.UUID, batch_id: uuid.UUID) -> None:
    """Pretend the worker died after the item's actions ran but before its result was recorded."""
    db.execute(update(AgentBatchItem).execution_options(synchronize_session=False).where(AgentBatchItem.id == item_id).values(status="running", updated_at=datetime.now(UTC) - timedelta(hours=1)))
    db.execute(update(AgentBatch).execution_options(synchronize_session=False).where(AgentBatch.id == batch_id).values(status="running", succeeded=0, needs_review=0, failed=0, finished_at=None))
    db.commit()


def test_rerun_of_crashed_bulk_item_does_not_repeat_side_effects(client, operator_headers, db, monkeypatch):
    # A real model words its proposals differently on every run; simulate that so payload hashes differ.
    original = ActionService._clean_payload

    def nondeterministic(self, action):
        payload = original(self, action)
        if action.tool_key == "crm.upsert_lead":
            payload = {**payload, "lead": {**payload["lead"], "summary": f"model wording {uuid.uuid4().hex[:6]}"}}
        return payload

    monkeypatch.setattr(ActionService, "_clean_payload", nondeterministic)
    r = client.post("/api/v1/agents/lead_qualification/batches", json={"items": [_lead(idem()[:6])]}, headers=operator_headers)
    assert r.status_code == 202, r.text
    batch = client.get(f"/api/v1/batches/{r.json()['id']}", headers=operator_headers).json()
    assert batch["status"] == "completed"
    item = db.execute(select(AgentBatchItem).where(AgentBatchItem.batch_id == uuid.UUID(batch["id"]))).scalar_one()
    before = _side_effects(db, batch["correlation_id"])
    assert before.get("crm.upsert_lead") == 1

    _make_stale(db, item.id, item.batch_id)
    assert process_batch_item(str(item.id))["status"] in {"completed", "needs_review"}

    db.expire_all()
    after = _side_effects(db, batch["correlation_id"])
    # The re-run proposes crm.update_lead (it now finds the lead) with different wording - yet performs nothing new.
    assert after == before, (before, after)
    b = db.get(AgentBatch, item.batch_id)
    assert b.status == "completed" and b.succeeded + b.needs_review == 1 and b.failed == 0


def test_result_from_a_superseded_claim_is_not_counted_twice(client, operator_headers, db):
    r = client.post("/api/v1/agents/lead_qualification/batches", json={"items": [_lead(idem()[:6])]}, headers=operator_headers)
    item = db.execute(select(AgentBatchItem).where(AgentBatchItem.batch_id == uuid.UUID(r.json()["id"]))).scalar_one()
    _make_stale(db, item.id, item.batch_id)
    # Re-run twice: the second sees a finished item and does nothing.
    process_batch_item(str(item.id))
    assert process_batch_item(str(item.id))["status"] in {"completed", "needs_review"}
    db.expire_all()
    b = db.get(AgentBatch, item.batch_id)
    assert b.succeeded + b.needs_review + b.failed == 1


def test_interrupted_non_idempotent_call_is_verified_not_repeated(db, demo_tenant, monkeypatch):
    spec = agent_registry.get("workflow_coordinator").spec
    ctx = AgentContext(tenant_id=str(demo_tenant.id), actor_id="system", correlation_id="t-" + idem(), permissions=["*"])
    key = "intr-" + idem()
    # A previous worker wrote the "attempted" marker and died before recording the result.
    db.add(ToolExecution(tenant_id=demo_tenant.id, tool_key="chat.post_message", provider="chat", mode="mock", side_effect=True, idempotency_key=key, request={"channel": "#ops", "text": "x"}, status="in_progress", attempt=1, correlation_id=ctx.correlation_id))
    db.commit()
    sent = {"n": 0}

    def post(self, *a, **kw):
        sent["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(mock_adapters.MockChatAdapter, "post_message", post)
    monkeypatch.setattr(mock_adapters.MockChatAdapter, "verify_action", lambda self, *a, **kw: None)  # provider can't tell
    out = ActionService(db, demo_tenant, ctx, spec).execute(ProposedAction(action_type="chat.notify", tool_key="chat.post_message", payload={"channel": "#ops", "text": "x"}, idempotency_key=key))
    assert out.outcome == "unknown" and "interrupted" in out.reason and sent["n"] == 0
    rec = db.execute(select(ToolExecution).where(ToolExecution.idempotency_key == key)).scalar_one()
    assert rec.status == "unknown"


def test_dead_batch_job_fails_the_item_so_the_batch_completes(client, operator_headers, db):
    r = client.post("/api/v1/agents/lead_qualification/batches", json={"items": [_lead(idem()[:6])]}, headers=operator_headers)
    item = db.execute(select(AgentBatchItem).where(AgentBatchItem.batch_id == uuid.UUID(r.json()["id"]))).scalar_one()
    _make_stale(db, item.id, item.batch_id)
    job = Job(kind="batch.item", payload={"item_id": str(item.id)}, tenant_id=item.tenant_id, status="running", attempts=5, max_attempts=5, locked_by="gone", lease_until=datetime.now(UTC) - timedelta(seconds=5), dedupe_key=f"test-dead:{idem()}")
    db.add(job)
    db.commit()
    assert jq.reap_expired_leases(db)["dead"] >= 1
    db.expire_all()
    assert db.get(AgentBatchItem, item.id).status == "failed"
    b = db.get(AgentBatch, item.batch_id)
    assert b.status == "completed" and b.failed == 1


def test_dead_copilot_job_closes_the_turn(client, operator_headers, db):
    s = client.post("/api/v1/copilot/sessions", json={"message": "Which approvals are pending?"}, headers=operator_headers).json()
    session = client.get(f"/api/v1/copilot/sessions/{s['id']}", headers=operator_headers).json()
    msg_id = uuid.UUID(session["messages"][-1]["id"])
    db.execute(update(CopilotMessage).execution_options(synchronize_session=False).where(CopilotMessage.id == msg_id).values(status="running", finished_at=None))
    job = Job(kind="copilot.turn", payload={"message_id": str(msg_id)}, status="running", attempts=3, max_attempts=3, locked_by="w-test", lease_until=datetime.now(UTC) + timedelta(seconds=60), dedupe_key=f"test-dead:{idem()}")
    db.add(job)
    db.commit()
    assert jq.fail_job(db, job.id, "w-test", "RuntimeError: boom") == "dead"
    db.expire_all()
    m = db.get(CopilotMessage, msg_id)
    assert m.status == "failed" and "boom" in (m.error or "")
