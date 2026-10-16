"""Ops Copilot, custom HTTP tools, bulk runs and the MCP server - end to end through the API."""

from __future__ import annotations

import json

import httpx
import pytest

from app.tools import custom as custom_mod
from tests.conftest import idem

# ---------------------------------------------------------------------------
# Copilot (offline planner; turns run inline in tests)
# ---------------------------------------------------------------------------


def _ask(client, headers, text, session_id=None):
    if session_id:
        r = client.post(f"/api/v1/copilot/sessions/{session_id}/messages", json={"message": text}, headers=headers)
    else:
        r = client.post("/api/v1/copilot/sessions", json={"message": text}, headers=headers)
    assert r.status_code == 202, r.text
    return client.get(f"/api/v1/copilot/sessions/{r.json()['id']}", headers=headers).json()


def test_copilot_status_lists_agents_and_tools(client, operator_headers):
    s = client.get("/api/v1/copilot/status", headers=operator_headers).json()
    assert s["mode"] == "offline_planner" and s["tool_counts"]["agent"] == 25 and s["tool_counts"]["tool"] >= 20
    assert any(t["name"] == "agent__inventory_forecasting" for t in s["tools"])


def test_copilot_multi_intent_turn_calls_agents_in_parallel(client, operator_headers):
    session = _ask(client, operator_headers, "Check inventory and tell me which tasks are overdue")
    reply = session["messages"][-1]
    assert reply["status"] == "done" and reply["mode"] == "offline_planner"
    tools = {st["tool_name"] for st in reply["steps"]}
    assert {"agent__inventory_forecasting", "agent__workflow_coordinator"} <= tools
    inv = next(st for st in reply["steps"] if st["tool_name"] == "agent__inventory_forecasting")
    assert inv["status"] == "needs_approval" and inv["approval_ids"] and inv["agent_run_id"]
    assert "approval" in reply["text"].lower()


def test_copilot_two_step_plan_and_follow_up(client, operator_headers):
    session = _ask(client, operator_headers, "Where is order ORD-5002?")
    steps = session["messages"][-1]["steps"]
    assert {"commerce__get_order", "commerce__get_shipment"} <= {s["tool_name"] for s in steps}
    assert all(s["status"] == "ok" for s in steps) and "FedEx" in session["messages"][-1]["text"]
    # Order-only phrasing: the planner fetches the order first, then the shipment in a second step.
    two_step = _ask(client, operator_headers, "Status of ORD-5001 please")
    names = [(s["tool_name"], s["iteration"]) for s in two_step["messages"][-1]["steps"]]
    assert ("commerce__get_order", 1) in names and ("commerce__get_shipment", 2) in names
    follow = _ask(client, operator_headers, "What needs my approval right now?", session_id=session["id"])
    assert len(follow["messages"]) == 4 and follow["messages"][-1]["steps"][0]["tool_name"] == "ops__list_pending_approvals"


def test_copilot_sessions_are_private(client, operator_headers, admin_headers, other_headers):
    session = _ask(client, operator_headers, "help")
    assert client.get(f"/api/v1/copilot/sessions/{session['id']}", headers=admin_headers).status_code == 403
    assert client.get(f"/api/v1/copilot/sessions/{session['id']}", headers=other_headers).status_code == 404
    assert all(s["id"] != session["id"] for s in client.get("/api/v1/copilot/sessions", headers=admin_headers).json())


def test_copilot_respects_permissions(client, viewer_headers):
    assert client.post("/api/v1/copilot/sessions", json={"message": "hi"}, headers=viewer_headers).status_code == 403


# ---------------------------------------------------------------------------
# Custom HTTP tools
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_http(monkeypatch):
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.path.startswith("/rates/"):
            return httpx.Response(200, json={"base": req.url.path.split("/")[-1], "EUR": 0.92})
        if req.url.path == "/refunds":
            return httpx.Response(201, json={"refund_id": "rf_1", "body": json.loads(req.content)})
        return httpx.Response(404, json={"error": "nope"})

    monkeypatch.setattr(custom_mod, "_transport_override", httpx.MockTransport(handler))
    monkeypatch.setattr(custom_mod, "_resolver_override", lambda host: ["93.184.216.34"])
    return calls


def test_custom_tool_lifecycle_and_copilot_use(client, admin_headers, operator_headers, fake_http):
    body = {"name": f"fx_rate_{idem()[:4]}", "description": "Get currency exchange rates for a base currency", "method": "GET", "url_template": "https://rates.example.com/rates/{base}",
            "auth_header_name": "X-Api-Token", "auth_secret": "super-secret-token", "input_schema": {"type": "object", "properties": {"base": {"type": "string"}}, "required": ["base"]}}
    r = client.post("/api/v1/custom-tools", json=body, headers=admin_headers)
    assert r.status_code == 201, r.text
    tool = r.json()
    assert tool["has_secret"] is True and "super-secret-token" not in r.text
    t = client.post(f"/api/v1/custom-tools/{tool['id']}/test", json={"input": {"base": "USD"}}, headers=admin_headers).json()
    assert t["ok"] and t["result"]["data"]["EUR"] == 0.92
    assert fake_http[-1].headers["X-Api-Token"] == "super-secret-token" and str(fake_http[-1].url) == "https://rates.example.com/rates/USD"
    bad = client.post(f"/api/v1/custom-tools/{tool['id']}/test", json={"input": {}}, headers=admin_headers).json()
    assert bad["ok"] is False and "required" in bad["error"]
    catalog = client.get("/api/v1/tools", headers=admin_headers).json()
    assert any(c["key"] == f"custom.{body['name']}" for c in catalog["custom"]) and len(catalog["builtin"]) >= 98
    status = client.get("/api/v1/copilot/status", headers=operator_headers).json()
    assert any(x["name"] == f"custom__{body['name']}" for x in status["tools"])


def test_side_effect_custom_tool_needs_approval_then_executes(client, db, demo_tenant, admin_headers, approver_headers, fake_http):
    from app.agents.base import AgentContext, ProposedAction
    from app.copilot.spec import COPILOT_SPEC
    from app.services.actions import ActionService

    name = f"refund_{idem()[:4]}"
    r = client.post("/api/v1/custom-tools", json={"name": name, "description": "Issue a refund in the billing system", "method": "POST", "url_template": "https://billing.example.com/refunds", "side_effect": True, "input_schema": {"type": "object", "properties": {"order_id": {"type": "string"}, "amount": {"type": "number"}}, "required": ["order_id", "amount"]}}, headers=admin_headers)
    assert r.status_code == 201 and r.json()["risk_level"] == "medium"
    assert client.post(f"/api/v1/custom-tools/{r.json()['id']}/test", json={"input": {"order_id": "ORD-1", "amount": 5}}, headers=admin_headers).status_code == 422
    ops_user = next(u for u in client.get("/api/v1/admin/users", headers=admin_headers).json() if u["email"] == "ops@acme-demo.test")
    ctx = AgentContext(tenant_id=str(demo_tenant.id), actor_id=ops_user["id"], correlation_id="c", permissions=ops_user["permissions"])
    out = ActionService(db, demo_tenant, ctx, COPILOT_SPEC).process_one(ProposedAction(action_type=f"custom.{name}", tool_key=f"custom.{name}", payload={"input": {"order_id": "ORD-5002", "amount": 12.5}}), evidence=[], context={})
    db.commit()
    assert out.outcome == "approval_pending" and not any(req.url.path == "/refunds" for req in fake_http)
    d = client.post(f"/api/v1/approvals/{out.approval_id}/decision", json={"decision": "approve", "note": "ok"}, headers=approver_headers)
    assert d.status_code == 200, d.text
    assert d.json()["status"] == "executed" and d.json()["execution"]["response"]["data"]["refund_id"] == "rf_1"
    assert sum(1 for req in fake_http if req.url.path == "/refunds") == 1


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1", "100.64.0.1", "::1", "::ffff:127.0.0.1", "::ffff:169.254.169.254", "fd00::1"])
def test_custom_tools_block_private_destinations(monkeypatch, ip):
    monkeypatch.setattr(custom_mod, "_resolver_override", lambda host: [ip])
    from app.core.errors import ValidationFailed

    with pytest.raises(ValidationFailed):
        custom_mod.assert_public_destination("https://looks-public.example.com/x")


def test_custom_tools_allow_public_destinations(monkeypatch):
    monkeypatch.setattr(custom_mod, "_resolver_override", lambda host: ["93.184.215.14", "2606:2800:21f:cb07:6820:80da:af6b:8b2c"])
    custom_mod.assert_public_destination("https://api.example.com/x")  # no exception


def test_custom_tool_definition_validation(client, admin_headers):
    bad = [
        {"name": "Bad Name", "url_template": "https://a.example.com"},
        {"name": "ok_name", "url_template": "ftp://a.example.com"},
        {"name": "ok_name2", "url_template": "https://{host}.example.com/x"},
        {"name": "ok_name3", "url_template": "https://a.example.com/{missing}"},
    ]
    for b in bad:
        r = client.post("/api/v1/custom-tools", json={"description": "something useful", **b}, headers=admin_headers)
        assert r.status_code == 422, b


# ---------------------------------------------------------------------------
# Bulk runs
# ---------------------------------------------------------------------------


def test_bulk_run_fans_out_and_tracks_progress(client, operator_headers):
    items = [{"lead": {"name": f"Bulk {i}", "email": f"bulk{i}-{idem()[:4]}@example.test", "company": "Example", "title": "CEO" if i % 2 else "Intern", "company_size": 120, "budget": 20000 if i % 2 else 100, "timeline": "this quarter", "message": "We need help automating onboarding."}} for i in range(12)]
    r = client.post("/api/v1/agents/lead_qualification/batches", json={"items": items, "name": "Q4 webinar leads"}, headers=operator_headers)
    assert r.status_code == 202, r.text
    batch = client.get(f"/api/v1/batches/{r.json()['id']}?limit=50", headers=operator_headers).json()
    assert batch["status"] == "completed" and batch["processed"] == 12 and batch["progress"] == 1.0
    assert batch["failed"] == 0 and len(batch["items"]) == 12 and all(i["agent_run_id"] for i in batch["items"])
    bad = client.post("/api/v1/agents/lead_qualification/batches", json={"items": [{"nope": 1}]}, headers=operator_headers)
    assert bad.status_code == 422 and "schema" in bad.json()["error"]["message"]


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------


def _rpc(client, key, method, params=None, rid=1):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}, headers={"Accept": "application/json, text/event-stream", "X-API-Key": key} if key else {"Accept": "application/json, text/event-stream"})
    assert r.status_code == 200, r.text
    return r.json()


def test_mcp_tools_list_and_call(client, admin_headers):
    key = client.post("/api/v1/admin/api-keys", json={"name": "mcp", "scopes": ["agents:read", "agents:run", "approvals:read", "documents:read", "workflows:read", "crm:*", "tasks:*"]}, headers=admin_headers).json()["plaintext"]
    init = _rpc(client, key, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "1"}})
    assert init["result"]["serverInfo"]["name"] == "OpsPilot AI"
    names = {t["name"] for t in _rpc(client, key, "tools/list")["result"]["tools"]}
    assert {"list_agents", "describe_agent", "run_agent", "start_workflow", "get_workflow_run", "list_pending_approvals", "search_knowledge"} <= names
    res = _rpc(client, key, "tools/call", {"name": "run_agent", "arguments": {"agent_key": "lead_qualification", "input": {"lead": {"name": "Mcp Lead", "email": f"mcp-{idem()[:5]}@example.test", "company": "Example", "title": "CEO", "company_size": 200, "budget": 50000, "timeline": "this quarter", "message": "We need to automate support."}}}})["result"]
    assert res.get("isError") is not True
    payload = res.get("structuredContent") or json.loads(res["content"][0]["text"])
    assert payload["data"]["qualified"] is True and payload["agent_run_id"]
    kb = _rpc(client, key, "tools/call", {"name": "search_knowledge", "arguments": {"query": "standard shipping days"}})["result"]
    assert "Shipping" in json.dumps(kb)


def test_mcp_rejects_missing_bad_or_underscoped_keys(client, admin_headers):
    no_key = _rpc(client, None, "tools/call", {"name": "list_agents", "arguments": {}})["result"]
    assert no_key["isError"] is True
    bad = _rpc(client, "opk_not_a_real_key", "tools/call", {"name": "list_agents", "arguments": {}})["result"]
    assert bad["isError"] is True and "Invalid" in json.dumps(bad)
    narrow = client.post("/api/v1/admin/api-keys", json={"name": "narrow", "scopes": ["agents:read"]}, headers=admin_headers).json()["plaintext"]
    denied = _rpc(client, narrow, "tools/call", {"name": "start_workflow", "arguments": {"workflow_key": "kpi_report", "input": {}}})["result"]
    assert denied["isError"] is True and "scope" in json.dumps(denied)
