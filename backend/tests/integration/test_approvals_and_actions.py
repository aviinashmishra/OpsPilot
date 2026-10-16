"""Approval binding, separation of duties, expiry, exactly-once execution, duplicate suppression,
transient failure handling and external-state reconciliation."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.agents.base import AgentContext, ProposedAction
from app.agents.registry import agent_registry
from app.core.errors import TransientIntegrationError
from app.db.models import Approval, ToolExecution, WorkflowRun
from app.integrations import mock_adapters
from app.services.actions import ActionService
from tests.conftest import idem

LEAD = {"lead": {"name": "Ana Silva", "email": "ana2@globex.test", "company": "Globex", "title": "VP Operations", "industry": "logistics", "company_size": 900, "budget": 80000, "timeline": "this quarter", "message": "We need to automate warehouse exception handling."}}


def _start(client, headers, key, inp):
    r = client.post("/api/v1/workflows", json={"workflow_key": key, "input": inp}, headers={**headers, "Idempotency-Key": idem()})
    assert r.status_code == 202, r.text
    return client.get(f"/api/v1/workflows/{r.json()['id']}", headers=headers).json()


def test_lead_workflow_waits_for_approval_then_resumes_on_approve(client, operator_headers, approver_headers):
    run = _start(client, operator_headers, "lead_to_crm", LEAD)
    assert run["status"] == "waiting_approval" and run["pending_approvals"]
    ap_id = run["pending_approvals"][0]
    ap = client.get(f"/api/v1/approvals/{ap_id}", headers=approver_headers).json()
    assert ap["tool_key"] == "email.send" and ap["status"] == "pending" and ap["evidence"]
    d = client.post(f"/api/v1/approvals/{ap_id}/decision", json={"decision": "approve", "note": "ok", "payload_hash": ap["payload_hash"]}, headers=approver_headers)
    assert d.status_code == 200, d.text
    assert d.json()["status"] == "executed" and d.json()["execution"]["outcome"] == "executed"
    run2 = client.get(f"/api/v1/workflows/{run['id']}", headers=operator_headers).json()
    assert run2["status"] == "completed" and run2["pending_approvals"] == []
    again = client.post(f"/api/v1/approvals/{ap_id}/decision", json={"decision": "approve"}, headers=approver_headers)
    assert again.status_code == 409  # exactly once


def test_invalid_start_input_is_rejected_before_a_run_exists(client, operator_headers, db):
    before = db.query(WorkflowRun).filter(WorkflowRun.workflow_key == "customer_query").count()
    r = client.post("/api/v1/workflows", json={"workflow_key": "customer_query", "input": {"message": "", "customer_id": ""}}, headers={**operator_headers, "Idempotency-Key": idem()})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation_failed" and r.json()["error"]["details"]["errors"][0]["loc"] == ["message"]
    assert db.query(WorkflowRun).filter(WorkflowRun.workflow_key == "customer_query").count() == before
    ok = client.post("/api/v1/workflows", json={"workflow_key": "customer_query", "input": {"message": "Where is my order ORD-5002?", "customer_id": "C-2003", "order_id": "ORD-5002"}}, headers={**operator_headers, "Idempotency-Key": idem()})
    assert ok.status_code == 202, ok.text


def test_slow_approval_does_not_time_out_the_run(client, operator_headers, approver_headers, db):
    """The deadline bounds execution, not human review: approving hours later still completes."""
    run = _start(client, operator_headers, "lead_to_crm", {"lead": {**LEAD["lead"], "email": "ana-slow@globex.test"}})
    row = db.get(WorkflowRun, uuid.UUID(run["id"]))
    now = datetime.now(UTC)
    row.deadline_at = now - timedelta(hours=1, minutes=50)  # 10 min budget, paused 2 h ago
    row.state = {**row.state, "waiting_since": (now - timedelta(hours=2)).isoformat()}
    db.commit()
    ap_id = run["pending_approvals"][0]
    ap = client.get(f"/api/v1/approvals/{ap_id}", headers=approver_headers).json()
    d = client.post(f"/api/v1/approvals/{ap_id}/decision", json={"decision": "approve", "payload_hash": ap["payload_hash"]}, headers=approver_headers)
    assert d.status_code == 200, d.text
    assert client.get(f"/api/v1/workflows/{run['id']}", headers=operator_headers).json()["status"] == "completed"


def test_rejection_resumes_without_execution(client, operator_headers, approver_headers, db):
    run = _start(client, operator_headers, "lead_to_crm", {"lead": {**LEAD["lead"], "email": "ana3@globex.test"}})
    ap_id = run["pending_approvals"][0]
    d = client.post(f"/api/v1/approvals/{ap_id}/decision", json={"decision": "reject", "note": "not now"}, headers=approver_headers)
    assert d.json()["status"] == "rejected"
    assert client.get(f"/api/v1/workflows/{run['id']}", headers=operator_headers).json()["status"] == "completed"
    assert db.execute(select(ToolExecution).where(ToolExecution.approval_id == uuid.UUID(ap_id))).first() is None


def test_viewer_and_api_key_cannot_decide(client, operator_headers, viewer_headers, admin_headers):
    run = _start(client, operator_headers, "lead_to_crm", {"lead": {**LEAD["lead"], "email": "ana4@globex.test"}})
    ap_id = run["pending_approvals"][0]
    assert client.post(f"/api/v1/approvals/{ap_id}/decision", json={"decision": "approve"}, headers=viewer_headers).status_code == 403
    k = client.post("/api/v1/admin/api-keys", json={"name": "k", "scopes": ["approvals:decide", "approvals:read"]}, headers=admin_headers).json()["plaintext"]
    assert client.post(f"/api/v1/approvals/{ap_id}/decision", json={"decision": "approve"}, headers={"X-API-Key": k}).status_code == 403


def test_separation_of_duties(client, admin_headers):
    """Whoever requested the action (by running the agent) cannot approve it - even an admin."""
    r = client.post("/api/v1/agents/sales_development/run", json={"input": {"lead_id": "L-1003"}, "mode": "workflow"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    ap_ids = [a["approval_id"] for a in r.json()["actions"] if a.get("approval_id")]
    assert ap_ids
    d = client.post(f"/api/v1/approvals/{ap_ids[0]}/decision", json={"decision": "approve"}, headers=admin_headers)
    assert d.status_code == 403 and "Separation" in d.json()["error"]["message"]


def test_payload_hash_mismatch_rejected(client, operator_headers, approver_headers):
    run = _start(client, operator_headers, "lead_to_crm", {"lead": {**LEAD["lead"], "email": "ana5@globex.test"}})
    ap_id = run["pending_approvals"][0]
    d = client.post(f"/api/v1/approvals/{ap_id}/decision", json={"decision": "approve", "payload_hash": "deadbeef"}, headers=approver_headers)
    assert d.status_code == 409


def test_tampered_payload_detected(client, operator_headers, approver_headers, db):
    run = _start(client, operator_headers, "lead_to_crm", {"lead": {**LEAD["lead"], "email": "ana6@globex.test"}})
    ap = db.get(Approval, uuid.UUID(run["pending_approvals"][0]))
    ap.action_payload = {**ap.action_payload, "to": "attacker@evil.test"}  # simulate tampering in storage
    db.commit()
    d = client.post(f"/api/v1/approvals/{ap.id}/decision", json={"decision": "approve"}, headers=approver_headers)
    assert d.status_code == 409 and "hash" in d.json()["error"]["message"]
    db.refresh(ap)
    assert ap.status == "superseded"


def test_expired_approval_cannot_execute(client, operator_headers, approver_headers, db):
    run = _start(client, operator_headers, "lead_to_crm", {"lead": {**LEAD["lead"], "email": "ana7@globex.test"}})
    ap = db.get(Approval, uuid.UUID(run["pending_approvals"][0]))
    ap.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    d = client.post(f"/api/v1/approvals/{ap.id}/decision", json={"decision": "approve"}, headers=approver_headers)
    assert d.status_code == 409
    listed = client.get("/api/v1/approvals?status=expired", headers=approver_headers).json()
    assert any(i["id"] == str(ap.id) for i in listed["items"])
    # Expiry counts as "not approved": the run moves on instead of waiting forever.
    assert client.get(f"/api/v1/workflows/{run['id']}", headers=operator_headers).json()["status"] == "completed"


def test_expiry_sweep_resumes_the_waiting_run(client, operator_headers, db):
    from app.services.approvals import expire_stale_approvals

    run = _start(client, operator_headers, "lead_to_crm", {"lead": {**LEAD["lead"], "email": "ana-exp@globex.test"}})
    ap = db.get(Approval, uuid.UUID(run["pending_approvals"][0]))
    ap.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert expire_stale_approvals(db) >= 1
    db.commit()
    assert client.get(f"/api/v1/workflows/{run['id']}", headers=operator_headers).json()["status"] == "completed"


def test_approving_is_blocked_during_emergency_disable(client, operator_headers, approver_headers, admin_headers):
    run = _start(client, operator_headers, "lead_to_crm", {"lead": {**LEAD["lead"], "email": "ana-stop@globex.test"}})
    ap_id = run["pending_approvals"][0]
    client.patch("/api/v1/admin/tenant", json={"emergency_disabled": True}, headers=admin_headers)
    try:
        d = client.post(f"/api/v1/approvals/{ap_id}/decision", json={"decision": "approve"}, headers=approver_headers)
        assert d.status_code == 409 and "emergency" in d.json()["error"]["message"]
        assert client.get(f"/api/v1/approvals/{ap_id}", headers=approver_headers).json()["status"] == "pending"
    finally:
        client.patch("/api/v1/admin/tenant", json={"emergency_disabled": False}, headers=admin_headers)


def test_required_permission_enforced_for_finance_actions(client, operator_headers, approver_headers, finance_headers):
    """Procurement POs require procurement:commit; the generic approver role has it, finance_approver too, viewer not."""
    run = _start(client, operator_headers, "quote_to_po", {"rfq_id": "RFQ-42"})
    ap = next(a for a in client.get(f"/api/v1/approvals?run_id={run['id']}&status=pending", headers=finance_headers).json()["items"] if a["tool_key"] == "procurement.create_purchase_order")
    assert ap["required_permission"] == "procurement:commit" and ap["risk_level"] == "critical"
    d = client.post(f"/api/v1/approvals/{ap['id']}/decision", json={"decision": "approve", "note": "budget ok"}, headers=finance_headers)
    assert d.status_code == 200 and d.json()["status"] == "executed"


def test_cancel_waiting_run_supersedes_approvals(client, operator_headers, approver_headers):
    run = _start(client, operator_headers, "lead_to_crm", {"lead": {**LEAD["lead"], "email": "ana8@globex.test"}})
    c = client.post(f"/api/v1/workflows/{run['id']}/cancel", headers=operator_headers)
    assert c.json()["status"] == "cancelled"
    ap = client.get(f"/api/v1/approvals/{run['pending_approvals'][0]}", headers=approver_headers).json()
    assert ap["status"] == "superseded"
    assert client.post(f"/api/v1/workflows/{run['id']}/cancel", headers=operator_headers).status_code == 409


# ---------------------------------------------------------------------------
# ActionService-level behaviour
# ---------------------------------------------------------------------------


def _ctx(tenant) -> AgentContext:
    return AgentContext(tenant_id=str(tenant.id), actor_id="system", correlation_id="t-" + idem(), permissions=["*"], workflow_run_id=None)


def test_duplicate_action_suppressed_by_idempotency_key(db, demo_tenant):
    spec = agent_registry.get("complaint_resolution").spec
    svc = ActionService(db, demo_tenant, _ctx(demo_tenant), spec)
    action = ProposedAction(action_type="helpdesk.create_ticket", tool_key="helpdesk.create_ticket", payload={"subject": "dup test", "description": "x"}, idempotency_key="dup-" + idem())
    first = svc.execute(action)
    second = svc.execute(action)
    assert first.outcome == "executed" and second.outcome == "duplicate" and second.tool_execution_id == first.tool_execution_id


def test_transient_failure_reconciles_instead_of_blind_retry(db, demo_tenant, monkeypatch):
    """chat.post_message is non-idempotent: after a timeout the platform must verify, not resend."""
    spec = agent_registry.get("workflow_coordinator").spec
    svc = ActionService(db, demo_tenant, _ctx(demo_tenant), spec)
    key = "unk-" + idem()
    original = mock_adapters.MockChatAdapter.post_message
    calls = {"n": 0}

    def flaky(self, *a, **kw):
        calls["n"] += 1
        original(self, *a, **kw)  # the message IS posted...
        raise TransientIntegrationError("timeout after write")  # ...but the response is lost

    monkeypatch.setattr(mock_adapters.MockChatAdapter, "post_message", flaky)
    action = ProposedAction(action_type="chat.notify", tool_key="chat.post_message", payload={"channel": "#ops", "text": "unknown outcome"}, idempotency_key=key)
    out = svc.execute(action)
    assert out.outcome == "executed" and out.reason == "verified after transient failure"
    rec = db.get(ToolExecution, uuid.UUID(out.tool_execution_id))
    assert rec.status == "reconciled" and rec.verification["exists"] is True and calls["n"] == 1
    monkeypatch.setattr(mock_adapters.MockChatAdapter, "post_message", original)
    out2 = svc.execute(action)
    assert out2.outcome == "duplicate"
    msgs = mock_adapters.MockChatAdapter(db, str(demo_tenant.id)).store.list("outbox")
    assert sum(1 for m in msgs if m.get("idempotency_key") == key) == 1


def test_unverifiable_transient_failure_is_not_retried(db, demo_tenant, monkeypatch):
    spec = agent_registry.get("workflow_coordinator").spec
    svc = ActionService(db, demo_tenant, _ctx(demo_tenant), spec)
    key = "unv-" + idem()

    def always_timeout(self, *a, **kw):
        raise TransientIntegrationError("timeout")

    monkeypatch.setattr(mock_adapters.MockChatAdapter, "post_message", always_timeout)
    monkeypatch.setattr(mock_adapters.MockChatAdapter, "verify_action", lambda self, *a, **kw: None)
    action = ProposedAction(action_type="chat.notify", tool_key="chat.post_message", payload={"channel": "#ops", "text": "x"}, idempotency_key=key)
    out = svc.execute(action)
    assert out.outcome == "unknown"
    out2 = svc.execute(action)
    assert out2.outcome == "unknown" and "not retrying" in out2.reason


def test_denied_action_recorded_not_executed(db, demo_tenant):
    spec = agent_registry.get("customer_support").spec
    svc = ActionService(db, demo_tenant, _ctx(demo_tenant), spec)
    out = svc.process([ProposedAction(action_type="x", tool_key="procurement.create_purchase_order", payload={})])
    assert out[0].outcome == "denied" and out[0].decision.policy_id == "platform.tool_allowlist"


def test_workflow_resume_after_restart(db, demo_tenant, client, operator_headers):
    """Simulate a worker crash mid-run: the run resumes from its last checkpoint."""
    from app.orchestration.engine import recover_stale_runs, start_run

    run = start_run(db, tenant_id=str(demo_tenant.id), workflow_key="kpi_report", input={"period_days": 7, "months": 2}, actor_id="system", enqueue=False)
    run.status = "running"
    run.heartbeat_at = datetime.now(UTC) - timedelta(hours=1)
    run.worker_id = "dead-worker"
    db.commit()
    recovered = recover_stale_runs(db, stale_after_seconds=60)
    assert str(run.id) in recovered
    db.refresh(run)
    assert run.status in {"completed", "waiting_approval"} and run.attempt == 1
    checkpoints = client.get(f"/api/v1/workflows/{run.id}", headers=operator_headers).json()["checkpoints"]
    assert any(c["node_key"] == "fanout" and c["status"] == "completed" for c in checkpoints)


@pytest.mark.parametrize("key", ["lead_to_crm", "customer_query"])
def test_duplicate_event_does_not_duplicate_logical_actions(client, operator_headers, db, demo_tenant, key):
    ext = idem()
    payload = LEAD if key == "lead_to_crm" else {"message": "How long does standard shipping take?", "customer_id": "C-2001"}
    et = "lead.created" if key == "lead_to_crm" else "support.message_received"
    e1 = client.post("/api/v1/events", json={"source": "t", "event_type": et, "external_id": ext, "payload": payload}, headers=operator_headers).json()
    e2 = client.post("/api/v1/events", json={"source": "t", "event_type": et, "external_id": ext, "payload": payload}, headers=operator_headers).json()
    assert e2["duplicate"] and e1["workflow_run_id"] == e2["workflow_run_id"]
    runs = db.execute(select(WorkflowRun).where(WorkflowRun.idempotency_key == f"event:{e1['id']}")).scalars().all()
    assert len(runs) == 1
