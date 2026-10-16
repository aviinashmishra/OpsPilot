"""Live provider adapters built on documented public REST APIs.

Only a focused subset of each provider's API is implemented - the operations
OpsPilot's tools need. Any tool method not implemented for a live provider
raises IntegrationNotConfigured instead of pretending to succeed.

These adapters are exercised by unit tests with httpx.MockTransport only;
they have NOT been run against real provider accounts in this repository.
Validate each with real sandbox credentials before production use.

References (public docs):
  Slack      https://api.slack.com/methods/chat.postMessage , auth.test
  HubSpot    https://developers.hubspot.com/docs/api/crm/contacts (CRM v3)
  SendGrid   https://docs.sendgrid.com/api-reference/mail-send/mail-send (v3)
  Jira Cloud https://developer.atlassian.com/cloud/jira/platform/rest/v3/
  Shopify    https://shopify.dev/docs/api/admin-rest (Admin REST)
  WhatsApp   https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
  Zendesk    https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/
"""

from __future__ import annotations

import base64
from typing import Any

from app.core.errors import IntegrationError, IntegrationNotConfigured
from app.integrations.base import ConnectionTestResult, HttpClientConfig, LiveHttpAdapter, VerificationResult


class _LiveBase(LiveHttpAdapter):
    implemented: tuple[str, ...] = ()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _unsupported(**_: Any) -> Any:
            raise IntegrationNotConfigured(f"Operation '{name}' is not implemented for live provider '{self.provider}'; use sandbox mode or extend the adapter")

        return _unsupported

    def _test(self, method: str, path: str, ok_message: str, **kwargs: Any) -> ConnectionTestResult:
        try:
            resp = self._request(method, path, **kwargs)
            return ConnectionTestResult(ok=True, mode="live", provider=self.provider, message=ok_message, details={"status": resp.status_code})
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(ok=False, mode="live", provider=self.provider, message=str(exc)[:300])


# ---------------------------------------------------------------------------
class SlackChatAdapter(_LiveBase):
    provider = "chat"
    display_name = "Slack"
    capabilities = ["post_message", "channels"]

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        super().__init__(HttpClientConfig(base_url="https://slack.com/api", headers={"Authorization": f"Bearer {credentials['bot_token']}", "Content-Type": "application/json; charset=utf-8"}, breaker_key="slack"))

    def test_connection(self) -> ConnectionTestResult:
        try:
            data = self._request("POST", "/auth.test").json()
            return ConnectionTestResult(ok=bool(data.get("ok")), mode="live", provider="chat", message=data.get("error") or f"Connected as {data.get('user')}", details={"team": data.get("team")})
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(ok=False, mode="live", provider="chat", message=str(exc)[:300])

    def post_message(self, channel: str, text: str, idempotency_key: str | None = None, **_: Any) -> dict[str, Any]:
        data = self._request("POST", "/chat.postMessage", json={"channel": channel, "text": text}, safe_to_retry=False).json()
        if not data.get("ok"):
            raise IntegrationError(f"Slack error: {data.get('error')}")
        return {"message_id": data.get("ts"), "channel": data.get("channel"), "status": "sent"}

    def list_channels(self) -> dict[str, Any]:
        data = self._request("GET", "/conversations.list", params={"limit": 200, "exclude_archived": "true"}).json()
        return {"items": [{"id": c["id"], "name": f"#{c['name']}"} for c in data.get("channels", [])]}


# ---------------------------------------------------------------------------
class HubSpotCRMAdapter(_LiveBase):
    provider = "crm"
    display_name = "HubSpot"
    capabilities = ["leads", "contacts"]

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        super().__init__(HttpClientConfig(base_url="https://api.hubapi.com", headers={"Authorization": f"Bearer {credentials['access_token']}"}, breaker_key="hubspot"))

    def test_connection(self) -> ConnectionTestResult:
        return self._test("GET", "/crm/v3/objects/contacts", "HubSpot CRM reachable", params={"limit": 1})

    def find_lead(self, email: str | None = None, phone: str | None = None, company: str | None = None) -> dict[str, Any]:
        filters = []
        if email:
            filters.append({"propertyName": "email", "operator": "EQ", "value": email})
        elif phone:
            filters.append({"propertyName": "phone", "operator": "EQ", "value": phone})
        elif company:
            filters.append({"propertyName": "company", "operator": "EQ", "value": company})
        if not filters:
            return {"matches": [], "count": 0}
        data = self._request("POST", "/crm/v3/objects/contacts/search", json={"filterGroups": [{"filters": filters}], "properties": ["email", "firstname", "lastname", "company", "phone", "jobtitle", "lifecyclestage"], "limit": 10}).json()
        matches = [{"id": r["id"], **r.get("properties", {})} for r in data.get("results", [])]
        return {"matches": matches, "count": len(matches)}

    def get_lead(self, lead_id: str) -> dict[str, Any]:
        data = self._request("GET", f"/crm/v3/objects/contacts/{lead_id}", params={"properties": "email,firstname,lastname,company,phone,jobtitle,lifecyclestage"}).json()
        return {"id": data["id"], **data.get("properties", {})}

    def upsert_lead(self, lead: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        props = {k: v for k, v in {"email": lead.get("email"), "firstname": lead.get("first_name"), "lastname": lead.get("last_name"), "company": lead.get("company"), "phone": lead.get("phone"), "jobtitle": lead.get("title")}.items() if v}
        existing = self.find_lead(email=lead.get("email")) if lead.get("email") else {"matches": []}
        if existing["matches"]:
            cid = existing["matches"][0]["id"]
            self._request("PATCH", f"/crm/v3/objects/contacts/{cid}", json={"properties": props}, safe_to_retry=True)
            return {"id": cid, "lead": {"id": cid, **props}}
        data = self._request("POST", "/crm/v3/objects/contacts", json={"properties": props}, safe_to_retry=False).json()
        return {"id": data["id"], "lead": {"id": data["id"], **props}}

    def update_lead(self, lead_id: str, fields: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        allowed = {k: v for k, v in fields.items() if isinstance(v, str | int | float | bool)}
        self._request("PATCH", f"/crm/v3/objects/contacts/{lead_id}", json={"properties": allowed})
        return {"id": lead_id, "lead": {"id": lead_id, **allowed}}

    def verify_action(self, method: str, request: dict[str, Any], external_ref: str | None) -> VerificationResult | None:
        email = (request.get("lead") or {}).get("email")
        if method == "upsert_lead" and email:
            found = self.find_lead(email=email)
            return VerificationResult(verified=True, exists=bool(found["matches"]), external_ref=found["matches"][0]["id"] if found["matches"] else None)
        return None


# ---------------------------------------------------------------------------
class SendGridEmailAdapter(_LiveBase):
    provider = "email"
    display_name = "SendGrid"
    capabilities = ["send"]

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self.from_email = config.get("from_email")
        if not self.from_email:
            raise IntegrationNotConfigured("SendGrid requires config.from_email (a verified sender)")
        super().__init__(HttpClientConfig(base_url="https://api.sendgrid.com", headers={"Authorization": f"Bearer {credentials['api_key']}"}, breaker_key="sendgrid"))

    def test_connection(self) -> ConnectionTestResult:
        return self._test("GET", "/v3/scopes", "SendGrid API key valid")

    def send(self, to: str, subject: str, body: str, template_id: str | None = None, idempotency_key: str | None = None, **_: Any) -> dict[str, Any]:
        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": self.from_email},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
            "custom_args": {"opspilot_idempotency_key": idempotency_key or ""},
        }
        resp = self._request("POST", "/v3/mail/send", json=payload, safe_to_retry=False)
        return {"message_id": resp.headers.get("X-Message-Id"), "status": "accepted"}


# ---------------------------------------------------------------------------
class JiraIssuesAdapter(_LiveBase):
    provider = "issues"
    display_name = "Jira Cloud"
    capabilities = ["issues", "search", "comments"]

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        site = config.get("site_url")
        if not site:
            raise IntegrationNotConfigured("Jira requires config.site_url, e.g. https://your-domain.atlassian.net")
        token = base64.b64encode(f"{credentials['email']}:{credentials['api_token']}".encode()).decode()
        super().__init__(HttpClientConfig(base_url=site.rstrip("/"), headers={"Authorization": f"Basic {token}", "Accept": "application/json"}, breaker_key="jira"))

    def test_connection(self) -> ConnectionTestResult:
        return self._test("GET", "/rest/api/3/myself", "Jira credentials valid")

    def search_issues(self, query: str = "", project: str | None = None, status: str | None = None, limit: int = 50) -> dict[str, Any]:
        clauses = []
        if project:
            clauses.append(f'project = "{project}"')
        if status:
            clauses.append(f'status = "{status}"')
        if query:
            safe = query.replace('"', " ")
            clauses.append(f'text ~ "{safe}"')
        jql = " AND ".join(clauses) or "order by created DESC"
        data = self._request("GET", "/rest/api/3/search", params={"jql": jql, "maxResults": limit, "fields": "summary,status,priority,description"}).json()
        items = [{"id": i["key"], "title": i["fields"].get("summary"), "status": (i["fields"].get("status") or {}).get("name"), "priority": (i["fields"].get("priority") or {}).get("name")} for i in data.get("issues", [])]
        return {"items": items, "count": len(items)}

    def create_issue(self, project: str, title: str, description: str = "", priority: str = "medium", issue_type: str = "task", idempotency_key: str | None = None, labels: list[str] | None = None, **_: Any) -> dict[str, Any]:
        body = {
            "fields": {
                "project": {"key": project},
                "summary": title[:250],
                "issuetype": {"name": issue_type.capitalize()},
                "labels": [*(labels or []), f"opspilot-{(idempotency_key or '')[-12:]}"] if idempotency_key else (labels or []),
                "description": {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": description[:30000] or title}]}]},
            }
        }
        data = self._request("POST", "/rest/api/3/issue", json=body, safe_to_retry=False).json()
        return {"key": data["key"], "issue": {"id": data["key"], "title": title}}

    def verify_action(self, method: str, request: dict[str, Any], external_ref: str | None) -> VerificationResult | None:
        key = request.get("idempotency_key")
        if method == "create_issue" and key:
            data = self._request("GET", "/rest/api/3/search", params={"jql": f'labels = "opspilot-{key[-12:]}"', "maxResults": 1}).json()
            issues = data.get("issues", [])
            return VerificationResult(verified=True, exists=bool(issues), external_ref=issues[0]["key"] if issues else None)
        return None


# ---------------------------------------------------------------------------
class ShopifyCommerceAdapter(_LiveBase):
    provider = "commerce"
    display_name = "Shopify"
    capabilities = ["products", "orders"]
    API_VERSION = "2024-07"

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        shop = config.get("shop_domain")
        if not shop:
            raise IntegrationNotConfigured("Shopify requires config.shop_domain, e.g. my-store.myshopify.com")
        super().__init__(HttpClientConfig(base_url=f"https://{shop}/admin/api/{self.API_VERSION}", headers={"X-Shopify-Access-Token": credentials["access_token"]}, breaker_key=f"shopify:{shop}"))

    def test_connection(self) -> ConnectionTestResult:
        return self._test("GET", "/shop.json", "Shopify Admin API reachable")

    def get_product(self, product_id: str) -> dict[str, Any]:
        p = self._request("GET", f"/products/{product_id}.json").json()["product"]
        v = (p.get("variants") or [{}])[0]
        return {"id": str(p["id"]), "title": p.get("title"), "description": p.get("body_html"), "price": float(v.get("price") or 0), "stock": v.get("inventory_quantity"), "tags": (p.get("tags") or "").split(", ")}

    def get_price_and_stock(self, product_id: str) -> dict[str, Any]:
        p = self.get_product(product_id)
        return {"product_id": product_id, "price": p["price"], "stock": p["stock"], "in_stock": (p["stock"] or 0) > 0}

    def get_order(self, order_id: str) -> dict[str, Any]:
        o = self._request("GET", f"/orders/{order_id}.json").json()["order"]
        return {"id": str(o["id"]), "status": o.get("fulfillment_status") or "unfulfilled", "financial_status": o.get("financial_status"), "total": float(o.get("total_price") or 0), "created_at": o.get("created_at"), "customer_id": str((o.get("customer") or {}).get("id") or "")}

    def list_orders(self, status: str | None = None, since_days: int | None = None, limit: int = 50) -> dict[str, Any]:
        data = self._request("GET", "/orders.json", params={"status": "any", "limit": min(limit, 250)}).json()
        items = [{"id": str(o["id"]), "status": o.get("fulfillment_status") or "unfulfilled", "total": float(o.get("total_price") or 0), "created_at": o.get("created_at")} for o in data.get("orders", [])]
        return {"items": items, "count": len(items)}


# ---------------------------------------------------------------------------
class WhatsAppCloudAdapter(_LiveBase):
    provider = "whatsapp"
    display_name = "WhatsApp Cloud API"
    capabilities = ["send_template", "send_text"]

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self.phone_number_id = config.get("phone_number_id")
        if not self.phone_number_id:
            raise IntegrationNotConfigured("WhatsApp requires config.phone_number_id")
        version = config.get("graph_api_version", "v20.0")
        super().__init__(HttpClientConfig(base_url=f"https://graph.facebook.com/{version}", headers={"Authorization": f"Bearer {credentials['access_token']}"}, breaker_key="whatsapp"))

    def test_connection(self) -> ConnectionTestResult:
        return self._test("GET", f"/{self.phone_number_id}", "WhatsApp phone number reachable")

    def send_template(self, to: str, template_name: str, parameters: list[str] | None = None, idempotency_key: str | None = None, language: str = "en_US") -> dict[str, Any]:
        components = [{"type": "body", "parameters": [{"type": "text", "text": p} for p in (parameters or [])]}] if parameters else []
        body = {"messaging_product": "whatsapp", "to": to, "type": "template", "template": {"name": template_name, "language": {"code": language}, "components": components}}
        data = self._request("POST", f"/{self.phone_number_id}/messages", json=body, safe_to_retry=False).json()
        return {"message_id": (data.get("messages") or [{}])[0].get("id"), "status": "accepted"}

    def send_text(self, to: str, text: str, idempotency_key: str | None = None) -> dict[str, Any]:
        body = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4096]}}
        data = self._request("POST", f"/{self.phone_number_id}/messages", json=body, safe_to_retry=False).json()
        return {"message_id": (data.get("messages") or [{}])[0].get("id"), "status": "accepted"}


# ---------------------------------------------------------------------------
class ZendeskHelpdeskAdapter(_LiveBase):
    provider = "helpdesk"
    display_name = "Zendesk"
    capabilities = ["tickets"]

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        sub = config.get("subdomain")
        if not sub:
            raise IntegrationNotConfigured("Zendesk requires config.subdomain")
        token = base64.b64encode(f"{credentials['email']}/token:{credentials['api_token']}".encode()).decode()
        super().__init__(HttpClientConfig(base_url=f"https://{sub}.zendesk.com/api/v2", headers={"Authorization": f"Basic {token}"}, breaker_key=f"zendesk:{sub}"))

    def test_connection(self) -> ConnectionTestResult:
        return self._test("GET", "/users/me.json", "Zendesk credentials valid")

    def create_ticket(self, subject: str, description: str, customer_id: str | None = None, category: str = "general", priority: str = "medium", sla_hours: int | None = None, idempotency_key: str | None = None, **_: Any) -> dict[str, Any]:
        prio = {"low": "low", "medium": "normal", "high": "high", "critical": "urgent"}.get(priority, "normal")
        body = {"ticket": {"subject": subject, "comment": {"body": description}, "priority": prio, "tags": [f"opspilot_{category}", f"opspilot_{(idempotency_key or '')[-12:]}"]}}
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        data = self._request("POST", "/tickets.json", json=body, headers=headers, safe_to_retry=bool(idempotency_key)).json()
        t = data["ticket"]
        return {"id": str(t["id"]), "ticket": {"id": str(t["id"]), "subject": t.get("subject"), "status": t.get("status")}}

    def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        t = self._request("GET", f"/tickets/{ticket_id}.json").json()["ticket"]
        return {"id": str(t["id"]), "subject": t.get("subject"), "status": t.get("status"), "priority": t.get("priority")}


LIVE_ADAPTERS: dict[tuple[str, str], type[_LiveBase]] = {
    ("chat", "slack"): SlackChatAdapter,
    ("crm", "hubspot"): HubSpotCRMAdapter,
    ("email", "sendgrid"): SendGridEmailAdapter,
    ("issues", "jira"): JiraIssuesAdapter,
    ("commerce", "shopify"): ShopifyCommerceAdapter,
    ("whatsapp", "meta_cloud_api"): WhatsAppCloudAdapter,
    ("helpdesk", "zendesk"): ZendeskHelpdeskAdapter,
}

REQUIRED_CREDENTIALS: dict[tuple[str, str], list[str]] = {
    ("chat", "slack"): ["bot_token"],
    ("crm", "hubspot"): ["access_token"],
    ("email", "sendgrid"): ["api_key"],
    ("issues", "jira"): ["email", "api_token"],
    ("commerce", "shopify"): ["access_token"],
    ("whatsapp", "meta_cloud_api"): ["access_token"],
    ("helpdesk", "zendesk"): ["email", "api_token"],
}


def build(family: str, live_provider: str, config: dict[str, Any], credentials: dict[str, Any]) -> _LiveBase | None:
    cls = LIVE_ADAPTERS.get((family, live_provider))
    if cls is None:
        return None
    missing = [k for k in REQUIRED_CREDENTIALS.get((family, live_provider), []) if not credentials.get(k)]
    if missing:
        raise IntegrationNotConfigured(f"Missing credentials for {live_provider}: {', '.join(missing)}")
    return cls(config, credentials)
