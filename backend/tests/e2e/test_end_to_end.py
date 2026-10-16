"""End-to-end scenarios required by the specification, driven through the public API."""

from app.evaluation.datasets import INVOICE_OK
from tests.conftest import idem


def _run(client, headers, key, inp):
    r = client.post("/api/v1/workflows", json={"workflow_key": key, "input": inp}, headers={**headers, "Idempotency-Key": idem()})
    assert r.status_code == 202, r.text
    return client.get(f"/api/v1/workflows/{r.json()['id']}", headers=headers).json()


def _approve_all(client, run, approver_headers, decision="approve"):
    out = []
    for ap_id in run["pending_approvals"]:
        ap = client.get(f"/api/v1/approvals/{ap_id}", headers=approver_headers).json()
        d = client.post(f"/api/v1/approvals/{ap_id}/decision", json={"decision": decision, "note": "e2e", "payload_hash": ap["payload_hash"]}, headers=approver_headers)
        assert d.status_code == 200, d.text
        out.append(d.json())
    return out


def test_meeting_transcript_to_task_creation(client, operator_headers, approver_headers):
    run = _run(client, operator_headers, "meeting_to_tasks", {"meeting_id": "MTG-1"})
    extract = run["state"]["nodes"]["extract"]
    assert extract["status"] in {"completed", "needs_approval"} and extract["data"]["action_items"]
    created = [a for a in extract["actions"] if a["tool_key"] == "platform.create_task" and a["outcome"] == "executed"]
    assert created
    tasks = client.get("/api/v1/tasks?q=pricing", headers=operator_headers).json()["items"]
    assert any("pricing" in t["title"].lower() and t["owner_name"] == "Dana Lee" and t["due_at"] for t in tasks)
    needs = [a for a in extract["data"]["action_items"] if a["needs_clarification"]]
    assert needs, "ambiguous owner/deadline items must ask for clarification"
    assert run["status"] in {"completed", "waiting_approval"}


def test_new_lead_to_qualified_crm_record(client, operator_headers, approver_headers, db, demo_tenant):
    from app.integrations.mock_adapters import MockCRMAdapter

    email = f"lead-{idem()[:6]}@globex.test"
    run = _run(client, operator_headers, "lead_to_crm", {"lead": {"name": "Ana Silva", "email": email, "company": "Globex", "title": "VP Operations", "industry": "logistics", "company_size": 900, "budget": 80000, "timeline": "this quarter", "message": "We need to automate warehouse exception handling."}, "source": "webform"})
    crm = MockCRMAdapter(db, str(demo_tenant.id))
    lead = crm.find_lead(email=email)["matches"][0]
    assert lead["status"] == "qualified" and lead["assigned_team"] == "Enterprise" and lead["score"] >= 60
    assert run["status"] == "waiting_approval"
    decisions = _approve_all(client, run, approver_headers)
    assert decisions and decisions[0]["status"] == "executed"
    outbox = db.execute(__import__("sqlalchemy").text("select count(*) from business_records where record_type='outbox'")).scalar()
    assert outbox >= 1
    assert client.get(f"/api/v1/workflows/{run['id']}", headers=operator_headers).json()["status"] == "completed"


def test_customer_query_to_verified_answer(client, operator_headers):
    run = _run(client, operator_headers, "customer_query", {"message": "How long does standard shipping take and what is your return window?", "customer_id": "C-2001", "channel": "email"})
    ans = run["state"]["nodes"]["answer"]["data"]
    assert run["status"] == "completed" and ans["escalate"] is False
    assert ans["citations"] and all(c["ref"].startswith("document:") for c in ans["citations"])
    assert "3-5" in ans["answer"]


def test_invoice_discrepancy_to_review_request(client, operator_headers, finance_headers):
    bad = INVOICE_OK.replace("Total Due: 4,800.00", "Total Due: 5,800.00")
    run = _run(client, operator_headers, "invoice_to_review", {"document_text": bad})
    data = run["state"]["nodes"]["process"]["data"]
    assert data["arithmetic_ok"] is False and data["payment_released"] is False
    assert run["status"] == "waiting_approval"
    ap = next(a for a in client.get(f"/api/v1/approvals?run_id={run['id']}", headers=finance_headers).json()["items"] if a["tool_key"] == "accounting.create_payable")
    assert ap["risk_level"] == "critical" and "total_mismatch" in str(ap["action_payload"])
    tasks = client.get("/api/v1/tasks?q=AP review", headers=operator_headers).json()["items"]
    assert tasks


def test_overdue_task_to_approved_escalation(client, operator_headers, approver_headers, admin_headers):
    users = client.get("/api/v1/admin/users", headers=admin_headers).json()
    t = client.post("/api/v1/tasks", json={"title": f"Overdue e2e {idem()[:5]}", "priority": "high", "owner_user_id": users[0]["id"], "due_at": "2020-01-01T00:00:00Z"}, headers=operator_headers).json()
    run = _run(client, operator_headers, "overdue_escalation", {})
    coord = run["state"]["nodes"]["coordinate"]["data"]
    assert any(o["task_id"] == t["id"] for o in coord["overdue"])
    assert run["status"] == "waiting_approval"
    _approve_all(client, run, approver_headers)
    task = client.get("/api/v1/tasks?q=Overdue e2e", headers=operator_headers).json()["items"]
    assert any(x["id"] == t["id"] and x["escalation_level"] >= 1 and "escalated" in x["labels"] for x in task)
    assert client.get(f"/api/v1/workflows/{run['id']}", headers=operator_headers).json()["status"] == "completed"


def test_kpi_data_to_evidence_backed_report(client, operator_headers):
    run = _run(client, operator_headers, "kpi_report", {"period_days": 14, "months": 3})
    bi = run["state"]["nodes"]["bi"]
    fin = run["state"]["nodes"]["finance"]
    assert bi["status"] == "completed" and bi["evidence_refs"] and "metric:" in bi["data"]["narrative"]
    assert fin["status"] in {"completed", "needs_approval"} and fin["data"]["totals"]["realized_savings_usd"] == 0.0
    assert run["status"] in {"completed", "waiting_approval"} and run["estimated_minutes_saved"] > 0


def test_failed_integration_to_recovery(client, operator_headers, admin_headers, db, demo_tenant, monkeypatch):
    """A transient provider failure inside a workflow marks the run for retry; after the provider recovers,
    the retry completes from the failed node without re-running completed nodes."""
    from app.core.errors import TransientIntegrationError
    from app.integrations import mock_adapters

    original = mock_adapters.MockCRMAdapter.find_lead
    state = {"fail": True}

    def flaky(self, *a, **kw):
        if state["fail"]:
            raise TransientIntegrationError("CRM unavailable")
        return original(self, *a, **kw)

    monkeypatch.setattr(mock_adapters.MockCRMAdapter, "find_lead", flaky)
    r = client.post("/api/v1/workflows", json={"workflow_key": "lead_to_crm", "input": {"lead": {"name": "Flaky", "email": f"flaky-{idem()[:5]}@x.test", "company": "X", "title": "CEO", "company_size": 100, "budget": 20000}}}, headers={**operator_headers, "Idempotency-Key": idem()})
    run = client.get(f"/api/v1/workflows/{r.json()['id']}", headers=operator_headers).json()
    assert run["status"] in {"pending", "failed"} and run["attempt"] >= 1
    state["fail"] = False
    monkeypatch.setattr(mock_adapters.MockCRMAdapter, "find_lead", original)
    from app.orchestration.engine import execute_run

    if run["status"] == "failed":
        client.post(f"/api/v1/workflows/{run['id']}/retry", headers=operator_headers)
    else:
        execute_run(run["id"])
    final = client.get(f"/api/v1/workflows/{run['id']}", headers=operator_headers).json()
    assert final["status"] in {"completed", "waiting_approval"}
    assert any(c["node_key"] == "qualify" and c["status"] == "completed" for c in final["checkpoints"])
    audit = client.get(f"/api/v1/audit-events?correlation_id={final['correlation_id']}", headers=admin_headers).json()
    assert audit["total"] >= 2 and any(e["action"] == "workflow.started" for e in audit["items"])
