"""New live connector operations, against httpx.MockTransport / a fake SMTP server (no network)."""

from __future__ import annotations

import json
import smtplib
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.errors import IntegrationError, IntegrationNotConfigured
from app.integrations import live
from app.integrations.base import reset_breakers
from app.integrations.hybrid import HybridAdapter, live_implements


def _patch(adapter, handler):
    adapter._client = httpx.Client(base_url=adapter._config.base_url, headers=adapter._config.headers, transport=httpx.MockTransport(handler))
    return adapter


@pytest.fixture(autouse=True)
def _breakers():
    reset_breakers()
    yield
    reset_breakers()


def test_chat_webhook_only_accepts_known_https_hosts_and_formats_payloads():
    for bad in ("http://hooks.slack.com/services/x", "https://evil.example.com/hook", "https://hooks.slack.com.evil.com/x"):
        with pytest.raises(IntegrationNotConfigured):
            live.WebhookChatAdapter({}, {"webhook_url": bad})
    sent: list[tuple[str, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append((req.url.host, json.loads(req.content)))
        return httpx.Response(200, text="ok")

    slack = _patch(live.WebhookChatAdapter({"channel_name": "#ops"}, {"webhook_url": "https://hooks.slack.com/services/T/B/x"}), handler)
    assert slack.post_message(channel="#anything", text="hello")["status"] == "sent"
    discord = _patch(live.WebhookChatAdapter({}, {"webhook_url": "https://discord.com/api/webhooks/1/abc"}), handler)
    discord.post_message(channel="x", text="hi")
    teams = _patch(live.WebhookChatAdapter({}, {"webhook_url": "https://acme.webhook.office.com/webhookb2/x"}), handler)
    assert teams.test_connection().ok
    assert sent[0] == ("hooks.slack.com", {"text": "hello"}) and sent[1][1] == {"content": "hi"} and "text" in sent[2][1]


def test_hubspot_notes_and_lists():
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        seen.append({"path": req.url.path, "body": body})
        if req.url.path == "/crm/v3/objects/notes":
            return httpx.Response(201, json={"id": "N1"})
        if req.url.path == "/crm/v3/objects/contacts/search":
            return httpx.Response(200, json={"results": [{"id": "7", "properties": {"email": "a@x.test", "firstname": "Ann", "lastname": "Lee", "lifecyclestage": "lead"}}]})
        return httpx.Response(404)

    hs = _patch(live.HubSpotCRMAdapter({}, {"access_token": "t"}), handler)
    out = hs.log_activity(lead_id="7", activity_type="call_summary", note="Discussed pricing")
    assert out["id"] == "N1"
    note = seen[0]["body"]
    assert note["associations"][0]["types"][0]["associationTypeId"] == 202 and "[call_summary] Discussed pricing" in note["properties"]["hs_note_body"]
    leads = hs.list_leads(status="lead")
    assert leads["items"][0] == {**leads["items"][0], "id": "7", "name": "Ann Lee", "status": "lead"}
    assert seen[-1]["body"]["filterGroups"][0]["filters"][0] == {"propertyName": "lifecyclestage", "operator": "EQ", "value": "lead"}


def test_zendesk_update_and_case_history():
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.method == "PUT":
            return httpx.Response(200, json={"ticket": {"id": 5, "status": "pending", "priority": "high", "subject": "S"}})
        if req.url.path == "/api/v2/search.json":
            return httpx.Response(200, json={"results": [{"id": 9, "subject": "Late", "status": "open", "requester_id": 42}]})
        return httpx.Response(404)

    zd = _patch(live.ZendeskHelpdeskAdapter({"subdomain": "acme"}, {"email": "a@x.test", "api_token": "t"}), handler)
    out = zd.update_ticket(ticket_id="5", fields={"status": "pending", "priority": "critical", "note": "Called the carrier"})
    sent = json.loads(calls[0].content)["ticket"]
    assert sent["priority"] == "urgent" and sent["comment"] == {"body": "Called the carrier", "public": False} and out["ticket"]["status"] == "pending"
    hist = zd.get_case_history(customer_id="kwame@sunrise.test")
    assert hist["items"][0]["id"] == "9" and "requester:kwame@sunrise.test" in calls[1].url.params["query"]
    with pytest.raises(IntegrationError):
        zd.update_ticket(ticket_id="5", fields={"unknown": 1})


def test_jira_status_change_uses_workflow_transitions():
    posted: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/transitions") and req.method == "GET":
            return httpx.Response(200, json={"transitions": [{"id": "31", "name": "Start progress", "to": {"name": "In Progress"}}, {"id": "41", "name": "Done", "to": {"name": "Done"}}]})
        if req.url.path.endswith("/transitions"):
            posted.append(json.loads(req.content))
            return httpx.Response(204)
        if req.method == "GET":
            return httpx.Response(200, json={"key": "OPS-1", "fields": {"summary": "S", "status": {"name": "In Progress"}}})
        return httpx.Response(204)

    jira = _patch(live.JiraIssuesAdapter({"site_url": "https://acme.atlassian.net"}, {"email": "a@x.test", "api_token": "t"}), handler)
    out = jira.update_issue(issue_key="OPS-1", fields={"status": "in progress"})
    assert posted == [{"transition": {"id": "31"}}] and out["issue"]["status"] == "In Progress"
    with pytest.raises(IntegrationError, match="no transition"):
        jira.update_issue(issue_key="OPS-1", fields={"status": "Archived"})


def test_shopify_sales_history_and_shipment():
    today = datetime.now(UTC)
    orders = [
        {"created_at": today.isoformat(), "line_items": [{"sku": "SKU-1", "quantity": 3}, {"sku": "OTHER", "quantity": 9}]},
        {"created_at": (today - timedelta(days=1)).isoformat(), "line_items": [{"sku": "SKU-1", "quantity": 2}]},
        {"created_at": (today - timedelta(days=40)).isoformat(), "line_items": [{"sku": "SKU-1", "quantity": 100}]},  # outside the window
    ]

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/orders.json"):
            return httpx.Response(200, json={"orders": orders})
        if req.url.path.endswith("/fulfillments.json"):
            return httpx.Response(200, json={"fulfillments": [{"tracking_company": "FedEx", "tracking_number": "7489", "shipment_status": "in_transit"}]})
        return httpx.Response(404)

    shop = _patch(live.ShopifyCommerceAdapter({"shop_domain": "acme.myshopify.com"}, {"access_token": "t"}), handler)
    hist = shop.get_sales_history(sku="SKU-1", days=30)
    assert hist["days"] == 30 and hist["daily_units"][-1] == 3 and hist["daily_units"][-2] == 2 and sum(hist["daily_units"]) == 5
    assert shop.get_shipment(order_id="1001") == {"found": True, "order_id": "1001", "carrier": "FedEx", "tracking_number": "7489", "status": "in_transit", "updated_at": None}


class _FakeSMTP:
    instances: list[_FakeSMTP] = []
    reject_login = False

    def __init__(self, host: str, port: int, timeout: int = 0, **_: object) -> None:
        self.host, self.port, self.sent, self.tls, self.logged_in = host, port, [], False, None
        _FakeSMTP.instances.append(self)

    def ehlo(self) -> None: ...

    def starttls(self, context: object = None) -> None:
        self.tls = True

    def login(self, user: str, password: str) -> None:
        if _FakeSMTP.reject_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.logged_in = user

    def send_message(self, msg: object) -> None:
        self.sent.append(msg)

    def quit(self) -> None: ...


def test_smtp_send_and_errors(monkeypatch):
    monkeypatch.setattr(live.smtplib, "SMTP", _FakeSMTP)
    _FakeSMTP.instances.clear()
    _FakeSMTP.reject_login = False
    with pytest.raises(IntegrationNotConfigured):
        live.SMTPEmailAdapter({}, {"username": "u@x.test", "password": "p"})
    smtp = live.SMTPEmailAdapter({"host": "smtp.gmail.com"}, {"username": "ops@acme.test", "password": "app-pass"})
    out = smtp.send(to="kwame@sunrise.test", subject="Your order", body="It ships today.", idempotency_key="approval:123")
    server = _FakeSMTP.instances[-1]
    msg = server.sent[0]
    assert out["status"] == "sent" and server.tls and server.logged_in == "ops@acme.test" and server.port == 587
    assert msg["From"] == "ops@acme.test" and msg["To"] == "kwame@sunrise.test" and msg["Subject"] == "Your order"
    _FakeSMTP.reject_login = True
    result = smtp.test_connection()
    assert not result.ok and "app password" in result.message


def test_hybrid_routes_each_operation_to_the_right_source():
    class Workspace:
        def get_price_list(self) -> dict:
            return {"items": [{"sku": "SKU-001"}]}

        def list_tickets(self) -> dict:  # provider data: must never be served from the workspace while live
            return {"items": ["sample"]}

    hs = live.HubSpotCRMAdapter({}, {"access_token": "t"})
    hybrid = HybridAdapter(hs, Workspace(), "crm")
    assert hybrid.source_of("find_lead") == "live" and live_implements(hs, "log_activity")
    assert hybrid.get_price_list() == {"items": [{"sku": "SKU-001"}], "source": "workspace"}
    assert hybrid.source_of("schedule_followup") == "unavailable"
    with pytest.raises(IntegrationNotConfigured):
        hybrid.schedule_followup(lead_id="1")
    zd = HybridAdapter(live.ZendeskHelpdeskAdapter({"subdomain": "acme"}, {"email": "e", "api_token": "t"}), Workspace(), "helpdesk")
    assert zd.source_of("list_tickets") == "live"  # implemented live: never falls back to sample tickets


def test_connection_fields_cover_every_live_adapter():
    assert set(live.CONNECTION_FIELDS) == set(live.LIVE_ADAPTERS)
    for spec in live.CONNECTION_FIELDS.values():
        assert spec["label"] and spec["help_url"].startswith("https://")
        assert all(f["store"] in {"config", "credentials"} for f in spec["fields"])
        assert any(f["secret"] for f in spec["fields"])  # every connector has at least one secret
    assert live.REQUIRED_CREDENTIALS[("email", "smtp")] == ["username", "password"]
