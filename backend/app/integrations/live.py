"""Live provider adapters built on documented public APIs.

Each adapter implements the operations OpsPilot's tools need for that system. Calls an adapter
does not implement are handled by `HybridAdapter` (integrations/hybrid.py): reads of data that
OpsPilot itself owns (price lists, policies, consent, templates…) come from the workspace's own
records; anything else raises IntegrationNotConfigured instead of pretending to succeed.

`CONNECTION_FIELDS` describes, per provider, the settings the Connect form asks for (label, help,
where the value is stored: non-secret `config` or encrypted `credentials`).

These adapters are exercised by unit tests with mocked transports; validate each with real
sandbox credentials before production use.

References (public docs):
  Slack      https://api.slack.com/methods/chat.postMessage , auth.test
  Webhooks   Slack incoming webhooks, Microsoft Teams workflows, Google Chat, Discord
  HubSpot    https://developers.hubspot.com/docs/api/crm/contacts (CRM v3), notes
  SendGrid   https://docs.sendgrid.com/api-reference/mail-send/mail-send (v3)
  SMTP       RFC 5321 / STARTTLS (Gmail, Outlook/Microsoft 365, any mail server)
  Jira Cloud https://developer.atlassian.com/cloud/jira/platform/rest/v3/
  Shopify    https://shopify.dev/docs/api/admin-rest (Admin REST)
  WhatsApp   https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
  Zendesk    https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/
"""

from __future__ import annotations

import base64
import smtplib
import ssl
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any
from urllib.parse import urlsplit

from app.core.errors import IntegrationError, IntegrationNotConfigured, NotFound, TransientIntegrationError
from app.integrations.base import (
    BaseAdapter,
    ConnectionTestResult,
    HttpClientConfig,
    LiveHttpAdapter,
    VerificationResult,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class _Unsupported:
    """Any operation an adapter does not define raises IntegrationNotConfigured."""

    provider: str

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _unsupported(*_: Any, **__: Any) -> Any:
            raise IntegrationNotConfigured(f"Operation '{name}' is not available for the connected {self.provider} system; switch it to sandbox or extend the adapter")

        return _unsupported


class _LiveBase(_Unsupported, LiveHttpAdapter):
    implemented: tuple[str, ...] = ()

    def _test(self, method: str, path: str, ok_message: str, **kwargs: Any) -> ConnectionTestResult:
        try:
            resp = self._request(method, path, **kwargs)
            return ConnectionTestResult(ok=True, mode="live", provider=self.provider, message=ok_message, details={"status": resp.status_code})
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(ok=False, mode="live", provider=self.provider, message=str(exc)[:300])


# ---------------------------------------------------------------------------
class SlackChatAdapter(_LiveBase):
    provider = "chat"
    display_name = "Slack (bot)"
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
_WEBHOOK_HOSTS = ("hooks.slack.com", ".webhook.office.com", ".logic.azure.com", ".environment.api.powerplatform.com", "chat.googleapis.com", "discord.com", "discordapp.com")


class WebhookChatAdapter(_LiveBase):
    """Post to one channel through an incoming-webhook URL (Slack, Microsoft Teams, Google Chat,
    Discord). No bot or app setup: paste the URL the chat tool gives you."""

    provider = "chat"
    display_name = "Chat webhook (Slack, Teams, Google Chat, Discord)"
    capabilities = ["post_message"]

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        url = urlsplit(str(credentials.get("webhook_url") or "").strip())
        host = (url.hostname or "").lower()
        if url.scheme != "https" or not any(host == h or (h.startswith(".") and host.endswith(h)) for h in _WEBHOOK_HOSTS):
            raise IntegrationNotConfigured("Use an https incoming-webhook URL from Slack, Microsoft Teams, Google Chat or Discord")
        self._path = url.path + (f"?{url.query}" if url.query else "")
        self._kind = "discord" if "discord" in host else "teams" if ("office.com" in host or "azure.com" in host or "powerplatform" in host) else "text"
        self.channel_name = str(config.get("channel_name") or "#webhook")
        super().__init__(HttpClientConfig(base_url=f"https://{host}", headers={"Content-Type": "application/json"}, breaker_key=f"webhook:{host}"))

    def _payload(self, text: str) -> dict[str, Any]:
        if self._kind == "discord":
            return {"content": text[:2000]}
        return {"text": text}

    def test_connection(self) -> ConnectionTestResult:
        try:
            self._request("POST", self._path, json=self._payload("OpsPilot is connected to this channel."), safe_to_retry=False)
            return ConnectionTestResult(ok=True, mode="live", provider="chat", message=f"Test message posted to {self.channel_name}")
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(ok=False, mode="live", provider="chat", message=str(exc)[:300])

    def post_message(self, channel: str, text: str, idempotency_key: str | None = None, **_: Any) -> dict[str, Any]:
        self._request("POST", self._path, json=self._payload(text), safe_to_retry=False)
        return {"message_id": idempotency_key or uuid.uuid4().hex, "channel": self.channel_name, "status": "sent"}

    def list_channels(self) -> dict[str, Any]:
        return {"items": [{"id": "webhook", "name": self.channel_name}]}


# ---------------------------------------------------------------------------
_HS_PROPS = "email,firstname,lastname,company,phone,jobtitle,lifecyclestage,createdate"


def _hs_contact(r: dict[str, Any]) -> dict[str, Any]:
    p = r.get("properties", {}) or {}
    name = " ".join(x for x in (p.get("firstname"), p.get("lastname")) if x).strip()
    return {"id": str(r["id"]), "name": name or p.get("email"), "first_name": p.get("firstname"), "email": p.get("email"), "phone": p.get("phone"), "company": p.get("company"), "title": p.get("jobtitle"), "status": p.get("lifecyclestage"), "created_at": p.get("createdate")}


class HubSpotCRMAdapter(_LiveBase):
    provider = "crm"
    display_name = "HubSpot"
    capabilities = ["leads", "contacts", "customers", "activities"]

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        super().__init__(HttpClientConfig(base_url="https://api.hubapi.com", headers={"Authorization": f"Bearer {credentials['access_token']}"}, breaker_key="hubspot"))

    def test_connection(self) -> ConnectionTestResult:
        return self._test("GET", "/crm/v3/objects/contacts", "HubSpot CRM reachable", params={"limit": 1})

    def _search(self, filters: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        data = self._request("POST", "/crm/v3/objects/contacts/search", json={"filterGroups": [{"filters": filters}] if filters else [], "properties": _HS_PROPS.split(","), "limit": min(max(limit, 1), 100)}).json()
        return [_hs_contact(r) for r in data.get("results", [])]

    def find_lead(self, email: str | None = None, phone: str | None = None, company: str | None = None) -> dict[str, Any]:
        field, value = ("email", email) if email else ("phone", phone) if phone else ("company", company) if company else (None, None)
        if not field:
            return {"matches": [], "count": 0}
        matches = self._search([{"propertyName": field, "operator": "EQ", "value": value}], 10)
        return {"matches": matches, "count": len(matches)}

    def get_lead(self, lead_id: str) -> dict[str, Any]:
        return _hs_contact(self._request("GET", f"/crm/v3/objects/contacts/{lead_id}", params={"properties": _HS_PROPS}).json())

    def list_leads(self, status: str | None = None, limit: int = 100) -> dict[str, Any]:
        items = self._search([{"propertyName": "lifecyclestage", "operator": "EQ", "value": status}] if status else [], limit)
        return {"items": items, "count": len(items)}

    def get_customer(self, customer_id: str) -> dict[str, Any]:
        return self.get_lead(customer_id)

    def list_customers(self, segment: str | None = None, limit: int = 500) -> dict[str, Any]:
        items = self._search([{"propertyName": "lifecyclestage", "operator": "EQ", "value": "customer"}], min(limit, 100))
        return {"items": items, "count": len(items)}

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

    def log_activity(self, lead_id: str, activity_type: str, note: str, idempotency_key: str | None = None) -> dict[str, Any]:
        body = {
            "properties": {"hs_timestamp": _now_iso(), "hs_note_body": f"[{activity_type}] {note}"[:65000]},
            "associations": [{"to": {"id": lead_id}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}]}],  # note -> contact
        }
        data = self._request("POST", "/crm/v3/objects/notes", json=body, safe_to_retry=False).json()
        return {"id": str(data["id"]), "activity": {"id": str(data["id"]), "lead_id": lead_id, "type": activity_type, "note": note}}

    def get_activity(self, lead_id: str) -> dict[str, Any]:
        data = self._request("POST", "/crm/v3/objects/notes/search", json={"filterGroups": [{"filters": [{"propertyName": "associations.contact", "operator": "EQ", "value": lead_id}]}], "properties": ["hs_note_body", "hs_timestamp"], "limit": 50}).json()
        items = [{"id": str(r["id"]), "lead_id": lead_id, "note": (r.get("properties") or {}).get("hs_note_body"), "at": (r.get("properties") or {}).get("hs_timestamp")} for r in data.get("results", [])]
        return {"items": items, "count": len(items)}

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
    capabilities = ["send", "templates"]

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self.from_email = config.get("from_email")
        if not self.from_email:
            raise IntegrationNotConfigured("SendGrid needs a From address (a verified sender)")
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

    def list_templates(self, category: str | None = None) -> dict[str, Any]:
        data = self._request("GET", "/v3/templates", params={"generations": "dynamic", "page_size": 50}).json()
        return {"items": [{"id": t["id"], "name": t.get("name")} for t in data.get("result", data.get("templates", []))]}


# ---------------------------------------------------------------------------
class SMTPEmailAdapter(_Unsupported, BaseAdapter):
    """Send through any mail server: Gmail / Google Workspace, Outlook / Microsoft 365, your own SMTP."""

    provider = "email"
    mode = "live"
    display_name = "SMTP (Gmail, Outlook, any mail server)"
    capabilities = ["send"]

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self.host = str(config.get("host") or "").strip()
        self.port = int(config.get("port") or 587)
        self.security = str(config.get("security") or ("ssl" if self.port == 465 else "starttls")).lower()
        self.username = str(credentials.get("username") or "").strip()
        self.password = str(credentials.get("password") or "")
        self.from_email = str(config.get("from_email") or self.username).strip()
        if not self.host or not self.from_email:
            raise IntegrationNotConfigured("SMTP needs a server host and a From address")

    def _connect(self) -> smtplib.SMTP:
        context = ssl.create_default_context()
        try:
            if self.security == "ssl":
                server: smtplib.SMTP = smtplib.SMTP_SSL(self.host, self.port, timeout=20, context=context)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=20)
                server.ehlo()
                if self.security == "starttls":
                    server.starttls(context=context)
                    server.ehlo()
            if self.username:
                server.login(self.username, self.password)
            return server
        except smtplib.SMTPAuthenticationError as exc:
            raise IntegrationError("The mail server rejected the username or password (for Gmail/Outlook use an app password)") from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise TransientIntegrationError(f"Cannot reach the mail server {self.host}:{self.port}: {exc}") from exc

    def test_connection(self) -> ConnectionTestResult:
        try:
            self._connect().quit()
            return ConnectionTestResult(ok=True, mode="live", provider="email", message=f"Signed in to {self.host}" + (f" as {self.username}" if self.username else ""))
        except Exception as exc:  # noqa: BLE001
            return ConnectionTestResult(ok=False, mode="live", provider="email", message=str(exc)[:300])

    def send(self, to: str, subject: str, body: str, template_id: str | None = None, idempotency_key: str | None = None, **_: Any) -> dict[str, Any]:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.from_email, to, subject
        msg["Message-ID"] = make_msgid(idstring=(idempotency_key or uuid.uuid4().hex)[-24:], domain=self.from_email.split("@")[-1] or None)
        msg.set_content(body)
        server = self._connect()
        try:
            server.send_message(msg)
        except smtplib.SMTPRecipientsRefused as exc:
            raise IntegrationError(f"The mail server refused the recipient {to}") from exc
        finally:
            try:
                server.quit()
            except (OSError, smtplib.SMTPException):
                pass
        return {"message_id": msg["Message-ID"], "status": "sent"}


# ---------------------------------------------------------------------------
def _adf(text: str) -> dict[str, Any]:
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text[:30000] or "-"}]}]}


class JiraIssuesAdapter(_LiveBase):
    provider = "issues"
    display_name = "Jira Cloud"
    capabilities = ["issues", "search", "comments", "projects"]

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        site = config.get("site_url")
        if not site:
            raise IntegrationNotConfigured("Jira needs your site URL, e.g. https://your-domain.atlassian.net")
        token = base64.b64encode(f"{credentials['email']}:{credentials['api_token']}".encode()).decode()
        super().__init__(HttpClientConfig(base_url=str(site).rstrip("/"), headers={"Authorization": f"Basic {token}", "Accept": "application/json"}, breaker_key="jira"))

    def test_connection(self) -> ConnectionTestResult:
        return self._test("GET", "/rest/api/3/myself", "Jira credentials valid")

    @staticmethod
    def _issue(i: dict[str, Any]) -> dict[str, Any]:
        f = i.get("fields", {}) or {}
        return {"id": i["key"], "key": i["key"], "title": f.get("summary"), "status": (f.get("status") or {}).get("name"), "priority": (f.get("priority") or {}).get("name"), "labels": f.get("labels") or [], "comments": ((f.get("comment") or {}).get("total"))}

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
        data = self._request("GET", "/rest/api/3/search", params={"jql": jql, "maxResults": limit, "fields": "summary,status,priority,labels"}).json()
        items = [self._issue(i) for i in data.get("issues", [])]
        return {"items": items, "count": len(items)}

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        return self._issue(self._request("GET", f"/rest/api/3/issue/{issue_key}", params={"fields": "summary,status,priority,labels,comment"}).json())

    def list_projects(self) -> dict[str, Any]:
        data = self._request("GET", "/rest/api/3/project/search", params={"maxResults": 50}).json()
        return {"items": [{"id": p["key"], "name": p.get("name")} for p in data.get("values", [])]}

    def create_issue(self, project: str, title: str, description: str = "", priority: str = "medium", issue_type: str = "task", idempotency_key: str | None = None, labels: list[str] | None = None, **_: Any) -> dict[str, Any]:
        body = {
            "fields": {
                "project": {"key": project},
                "summary": title[:250],
                "issuetype": {"name": issue_type.capitalize()},
                "labels": [*(labels or []), f"opspilot-{(idempotency_key or '')[-12:]}"] if idempotency_key else (labels or []),
                "description": _adf(description or title),
            }
        }
        data = self._request("POST", "/rest/api/3/issue", json=body, safe_to_retry=False).json()
        return {"key": data["key"], "issue": {"id": data["key"], "title": title}}

    def add_comment(self, issue_key: str, body: str, idempotency_key: str | None = None) -> dict[str, Any]:
        data = self._request("POST", f"/rest/api/3/issue/{issue_key}/comment", json={"body": _adf(body)}, safe_to_retry=False).json()
        return {"key": issue_key, "comment_id": str(data.get("id")), "duplicate_suppressed": False}

    def update_issue(self, issue_key: str, fields: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        if fields.get("title") or fields.get("summary"):
            updates["summary"] = str(fields.get("title") or fields.get("summary"))[:250]
        if fields.get("priority"):
            updates["priority"] = {"name": str(fields["priority"]).capitalize()}
        if isinstance(fields.get("labels"), list):
            updates["labels"] = [str(x) for x in fields["labels"]]
        if updates:
            self._request("PUT", f"/rest/api/3/issue/{issue_key}", json={"fields": updates})
        if fields.get("status"):
            wanted = str(fields["status"]).lower()
            transitions = self._request("GET", f"/rest/api/3/issue/{issue_key}/transitions").json().get("transitions", [])
            match = next((t for t in transitions if wanted in {str(t.get("name", "")).lower(), str((t.get("to") or {}).get("name", "")).lower()}), None)
            if match is None:
                raise IntegrationError(f"Jira has no transition to status '{fields['status']}' for {issue_key}", details={"available": [t.get("name") for t in transitions]})
            self._request("POST", f"/rest/api/3/issue/{issue_key}/transitions", json={"transition": {"id": match["id"]}}, safe_to_retry=False)
        return {"issue": self.get_issue(issue_key), "key": issue_key}

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
    capabilities = ["products", "orders", "inventory", "fulfillments"]
    API_VERSION = "2024-07"

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        shop = str(config.get("shop_domain") or "").strip().removeprefix("https://").strip("/")
        if not shop:
            raise IntegrationNotConfigured("Shopify needs your shop domain, e.g. my-store.myshopify.com")
        super().__init__(HttpClientConfig(base_url=f"https://{shop}/admin/api/{self.API_VERSION}", headers={"X-Shopify-Access-Token": credentials["access_token"]}, breaker_key=f"shopify:{shop}"))

    def test_connection(self) -> ConnectionTestResult:
        return self._test("GET", "/shop.json", "Shopify Admin API reachable")

    @staticmethod
    def _product(p: dict[str, Any]) -> dict[str, Any]:
        v = (p.get("variants") or [{}])[0]
        return {"id": str(p["id"]), "title": p.get("title"), "description": p.get("body_html"), "category": p.get("product_type"), "price": float(v.get("price") or 0), "stock": v.get("inventory_quantity"), "sku": v.get("sku"), "tags": [t for t in (p.get("tags") or "").split(", ") if t]}

    def _products(self, limit: int = 250) -> list[dict[str, Any]]:
        return self._request("GET", "/products.json", params={"limit": min(limit, 250)}).json().get("products", [])

    def get_product(self, product_id: str) -> dict[str, Any]:
        return self._product(self._request("GET", f"/products/{product_id}.json").json()["product"])

    def search_products(self, query: str = "", category: str | None = None, max_price: float | None = None, limit: int = 10) -> dict[str, Any]:
        terms = [t for t in (query or "").lower().replace(",", " ").split() if len(t) > 2]
        scored = []
        for p in map(self._product, self._products()):
            if category and (p.get("category") or "").lower() != category.lower():
                continue
            if max_price is not None and p["price"] > max_price:
                continue
            text = f"{p['title']} {p['description'] or ''} {' '.join(p['tags'])} {p.get('category') or ''}".lower()
            score = sum(1 for t in terms if t in text)
            if not terms or score:
                scored.append((score, p))
        scored.sort(key=lambda x: (-x[0], x[1]["price"]))
        return {"items": [p for _, p in scored[:limit]], "count": len(scored)}

    def get_price_and_stock(self, product_id: str) -> dict[str, Any]:
        p = self.get_product(product_id)
        return {"product_id": product_id, "price": p["price"], "stock": p["stock"], "in_stock": (p["stock"] or 0) > 0}

    def list_inventory(self, limit: int = 500) -> dict[str, Any]:
        items = [{"sku": v.get("sku") or str(v.get("id")), "product_id": str(p["id"]), "title": f"{p.get('title')} {v.get('title') if v.get('title') != 'Default Title' else ''}".strip(), "on_hand": v.get("inventory_quantity") or 0} for p in self._products() for v in (p.get("variants") or [])]
        return {"items": items[:limit]}

    def get_inventory(self, sku: str) -> dict[str, Any]:
        found = next((i for i in self.list_inventory()["items"] if i["sku"] == sku), None)
        if not found:
            raise NotFound(f"No inventory record for SKU {sku}")
        return found

    def get_order(self, order_id: str) -> dict[str, Any]:
        o = self._request("GET", f"/orders/{order_id}.json").json()["order"]
        return {"id": str(o["id"]), "status": o.get("fulfillment_status") or "unfulfilled", "financial_status": o.get("financial_status"), "total": float(o.get("total_price") or 0), "created_at": o.get("created_at"), "customer_id": str((o.get("customer") or {}).get("id") or ""), "note": o.get("note"), "tags": o.get("tags")}

    def list_orders(self, status: str | None = None, since_days: int | None = None, limit: int = 50) -> dict[str, Any]:
        data = self._request("GET", "/orders.json", params={"status": "any", "limit": min(limit, 250)}).json()
        items = [{"id": str(o["id"]), "status": o.get("fulfillment_status") or "unfulfilled", "total": float(o.get("total_price") or 0), "created_at": o.get("created_at")} for o in data.get("orders", [])]
        if status:
            items = [i for i in items if i["status"] == status]
        return {"items": items, "count": len(items)}

    def get_sales_history(self, sku: str, days: int = 90) -> dict[str, Any]:
        """Units sold per day for a SKU over the last `days`, from real orders (oldest day first)."""
        days = max(1, min(int(days), 365))
        start = datetime.now(UTC).date().toordinal() - days + 1
        since = datetime.fromordinal(start).replace(tzinfo=UTC).isoformat()
        units = [0] * days
        params: dict[str, Any] | None = {"status": "any", "created_at_min": since, "limit": 250, "fields": "created_at,line_items"}
        path = "/orders.json"
        for _ in range(8):  # up to 2,000 orders
            resp = self._request("GET", path, params=params)
            for o in resp.json().get("orders", []):
                idx = datetime.fromisoformat(str(o.get("created_at")).replace("Z", "+00:00")).date().toordinal() - start
                if 0 <= idx < days:
                    units[idx] += sum(int(li.get("quantity") or 0) for li in o.get("line_items", []) if li.get("sku") == sku)
            nxt = resp.links.get("next", {}).get("url") if hasattr(resp, "links") else None
            if not nxt:
                break
            path, params = urlsplit(nxt).path.split(f"/admin/api/{self.API_VERSION}", 1)[-1] + "?" + urlsplit(nxt).query, None
        return {"sku": sku, "daily_units": units, "days": days}

    def get_shipment(self, order_id: str) -> dict[str, Any]:
        fulfillments = self._request("GET", f"/orders/{order_id}/fulfillments.json").json().get("fulfillments", [])
        if not fulfillments:
            return {"order_id": order_id, "found": False}
        f = fulfillments[-1]
        return {"found": True, "order_id": order_id, "carrier": f.get("tracking_company"), "tracking_number": f.get("tracking_number"), "status": f.get("shipment_status") or f.get("status"), "updated_at": f.get("updated_at")}

    def update_order(self, order_id: str, fields: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        allowed = {k: (", ".join(v) if k == "tags" and isinstance(v, list) else v) for k, v in fields.items() if k in {"note", "tags", "email"}}
        if not allowed:
            raise IntegrationError("Shopify orders can only be updated with note, tags or email from OpsPilot")
        self._request("PUT", f"/orders/{order_id}.json", json={"order": {"id": int(order_id) if str(order_id).isdigit() else order_id, **allowed}})
        return {"order": self.get_order(order_id), "id": order_id}

    def update_listing(self, product_id: str, fields: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        product: dict[str, Any] = {}
        if fields.get("title"):
            product["title"] = str(fields["title"])
        if fields.get("description") is not None:
            product["body_html"] = str(fields["description"])
        if isinstance(fields.get("tags"), list):
            product["tags"] = ", ".join(str(t) for t in fields["tags"])
        if product:
            self._request("PUT", f"/products/{product_id}.json", json={"product": {"id": int(product_id) if str(product_id).isdigit() else product_id, **product}})
        if fields.get("price") is not None:
            raw = self._request("GET", f"/products/{product_id}.json").json()["product"]
            variant = (raw.get("variants") or [{}])[0]
            if variant.get("id"):
                self._request("PUT", f"/variants/{variant['id']}.json", json={"variant": {"id": variant["id"], "price": str(fields["price"])}})
        return {"product": self.get_product(product_id), "id": product_id}


# ---------------------------------------------------------------------------
class WhatsAppCloudAdapter(_LiveBase):
    provider = "whatsapp"
    display_name = "WhatsApp Cloud API"
    capabilities = ["send_template", "send_text"]

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self.phone_number_id = config.get("phone_number_id")
        if not self.phone_number_id:
            raise IntegrationNotConfigured("WhatsApp needs your phone number ID")
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
    capabilities = ["tickets", "case_history"]
    _PRIORITY_IN = {"low": "low", "medium": "normal", "normal": "normal", "high": "high", "critical": "urgent", "urgent": "urgent"}

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        sub = str(config.get("subdomain") or "").strip().removesuffix(".zendesk.com")
        if not sub:
            raise IntegrationNotConfigured("Zendesk needs your subdomain (the part before .zendesk.com)")
        token = base64.b64encode(f"{credentials['email']}/token:{credentials['api_token']}".encode()).decode()
        super().__init__(HttpClientConfig(base_url=f"https://{sub}.zendesk.com/api/v2", headers={"Authorization": f"Basic {token}"}, breaker_key=f"zendesk:{sub}"))

    def test_connection(self) -> ConnectionTestResult:
        return self._test("GET", "/users/me.json", "Zendesk credentials valid")

    @staticmethod
    def _ticket(t: dict[str, Any]) -> dict[str, Any]:
        return {"id": str(t["id"]), "subject": t.get("subject"), "status": t.get("status"), "priority": t.get("priority"), "customer_id": str(t.get("requester_id") or ""), "created_at": t.get("created_at"), "tags": t.get("tags") or []}

    def create_ticket(self, subject: str, description: str, customer_id: str | None = None, category: str = "general", priority: str = "medium", sla_hours: int | None = None, idempotency_key: str | None = None, **_: Any) -> dict[str, Any]:
        body = {"ticket": {"subject": subject, "comment": {"body": description}, "priority": self._PRIORITY_IN.get(priority, "normal"), "tags": [f"opspilot_{category}", f"opspilot_{(idempotency_key or '')[-12:]}"]}}
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        data = self._request("POST", "/tickets.json", json=body, headers=headers, safe_to_retry=bool(idempotency_key)).json()
        t = data["ticket"]
        return {"id": str(t["id"]), "ticket": {"id": str(t["id"]), "subject": t.get("subject"), "status": t.get("status")}}

    def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        return self._ticket(self._request("GET", f"/tickets/{ticket_id}.json").json()["ticket"])

    def list_tickets(self, customer_id: str | None = None, status: str | None = None, limit: int = 100) -> dict[str, Any]:
        if customer_id:
            query = f"type:ticket requester:{customer_id}" + (f" status:{status}" if status else "")
            rows = self._request("GET", "/search.json", params={"query": query, "per_page": min(limit, 100)}).json().get("results", [])
        else:
            rows = self._request("GET", "/tickets.json", params={"per_page": min(limit, 100), "sort_by": "created_at", "sort_order": "desc"}).json().get("tickets", [])
            if status:
                rows = [r for r in rows if r.get("status") == status]
        items = [self._ticket(r) for r in rows]
        return {"items": items, "count": len(items)}

    def get_case_history(self, customer_id: str) -> dict[str, Any]:
        return self.list_tickets(customer_id=customer_id, limit=100)

    def update_ticket(self, ticket_id: str, fields: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        ticket: dict[str, Any] = {}
        if fields.get("status"):
            ticket["status"] = str(fields["status"])
        if fields.get("priority"):
            ticket["priority"] = self._PRIORITY_IN.get(str(fields["priority"]), "normal")
        if fields.get("subject"):
            ticket["subject"] = str(fields["subject"])
        if isinstance(fields.get("tags"), list):
            ticket["tags"] = [str(t) for t in fields["tags"]]
        note = fields.get("note") or fields.get("comment")
        if note:
            ticket["comment"] = {"body": str(note), "public": bool(fields.get("public", False))}
        if not ticket:
            raise IntegrationError("Nothing to update on the Zendesk ticket (status, priority, subject, tags or note)")
        t = self._request("PUT", f"/tickets/{ticket_id}.json", json={"ticket": ticket}).json()["ticket"]
        return {"ticket": self._ticket(t), "id": str(t["id"])}


# ---------------------------------------------------------------------------
LIVE_ADAPTERS: dict[tuple[str, str], type[BaseAdapter]] = {
    ("chat", "slack"): SlackChatAdapter,
    ("chat", "webhook"): WebhookChatAdapter,
    ("crm", "hubspot"): HubSpotCRMAdapter,
    ("email", "smtp"): SMTPEmailAdapter,
    ("email", "sendgrid"): SendGridEmailAdapter,
    ("issues", "jira"): JiraIssuesAdapter,
    ("commerce", "shopify"): ShopifyCommerceAdapter,
    ("whatsapp", "meta_cloud_api"): WhatsAppCloudAdapter,
    ("helpdesk", "zendesk"): ZendeskHelpdeskAdapter,
}


def _f(key: str, label: str, *, store: str, secret: bool = False, required: bool = True, placeholder: str = "", help: str = "", options: list[str] | None = None) -> dict[str, Any]:  # noqa: A002
    return {"key": key, "label": label, "store": store, "secret": secret, "required": required, "placeholder": placeholder, "help": help, **({"options": options} if options else {})}


# What the Connect form asks for. store="credentials" values are encrypted and never returned.
CONNECTION_FIELDS: dict[tuple[str, str], dict[str, Any]] = {
    ("chat", "webhook"): {"label": "Chat webhook (Slack, Teams, Google Chat, Discord)", "help_url": "https://api.slack.com/messaging/webhooks", "fields": [
        _f("webhook_url", "Incoming webhook URL", store="credentials", secret=True, placeholder="https://hooks.slack.com/services/…", help="Create an incoming webhook for the channel in Slack, Teams (Workflows), Google Chat or Discord and paste its URL."),
        _f("channel_name", "Channel name", store="config", required=False, placeholder="#ops", help="Shown in OpsPilot; the webhook decides the real channel."),
    ]},
    ("chat", "slack"): {"label": "Slack (bot)", "help_url": "https://api.slack.com/authentication/basics", "fields": [
        _f("bot_token", "Bot token", store="credentials", secret=True, placeholder="xoxb-…", help="Slack app → OAuth & Permissions → Bot User OAuth Token (scopes chat:write, channels:read). Invite the bot to the channels it should post in."),
    ]},
    ("crm", "hubspot"): {"label": "HubSpot", "help_url": "https://developers.hubspot.com/docs/api/private-apps", "fields": [
        _f("access_token", "Private app access token", store="credentials", secret=True, placeholder="pat-…", help="HubSpot → Settings → Integrations → Private apps → Create, with crm.objects.contacts read/write and crm.objects.notes scopes."),
    ]},
    ("email", "smtp"): {"label": "SMTP (Gmail, Outlook, any mail server)", "help_url": "https://support.google.com/accounts/answer/185833", "fields": [
        _f("host", "SMTP server", store="config", placeholder="smtp.gmail.com", help="Gmail: smtp.gmail.com · Outlook/Microsoft 365: smtp.office365.com"),
        _f("port", "Port", store="config", required=False, placeholder="587", help="587 (STARTTLS, default) or 465 (SSL)"),
        _f("security", "Security", store="config", required=False, placeholder="starttls", options=["starttls", "ssl", "none"]),
        _f("username", "Username", store="credentials", placeholder="you@company.com"),
        _f("password", "Password / app password", store="credentials", secret=True, help="For Gmail and Outlook with 2-step verification, create an app password."),
        _f("from_email", "From address", store="config", required=False, placeholder="ops@company.com", help="Defaults to the username."),
    ]},
    ("email", "sendgrid"): {"label": "SendGrid", "help_url": "https://docs.sendgrid.com/ui/account-and-settings/api-keys", "fields": [
        _f("api_key", "API key", store="credentials", secret=True, placeholder="SG.…", help="SendGrid → Settings → API Keys (Mail Send permission)."),
        _f("from_email", "From address (verified sender)", store="config", placeholder="ops@company.com"),
    ]},
    ("issues", "jira"): {"label": "Jira Cloud", "help_url": "https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/", "fields": [
        _f("site_url", "Site URL", store="config", placeholder="https://your-company.atlassian.net"),
        _f("email", "Account email", store="credentials", placeholder="you@company.com"),
        _f("api_token", "API token", store="credentials", secret=True, help="id.atlassian.com → Security → API tokens."),
    ]},
    ("commerce", "shopify"): {"label": "Shopify", "help_url": "https://help.shopify.com/en/manual/apps/app-types/custom-apps", "fields": [
        _f("shop_domain", "Shop domain", store="config", placeholder="my-store.myshopify.com"),
        _f("access_token", "Admin API access token", store="credentials", secret=True, placeholder="shpat_…", help="Shopify admin → Apps → Develop apps → create an app with read/write products, orders and inventory."),
    ]},
    ("whatsapp", "meta_cloud_api"): {"label": "WhatsApp Cloud API", "help_url": "https://developers.facebook.com/docs/whatsapp/cloud-api/get-started", "fields": [
        _f("phone_number_id", "Phone number ID", store="config", placeholder="1234567890", help="Meta for Developers → your app → WhatsApp → API Setup."),
        _f("access_token", "Access token", store="credentials", secret=True, help="Use a permanent System User token for production."),
    ]},
    ("helpdesk", "zendesk"): {"label": "Zendesk", "help_url": "https://support.zendesk.com/hc/en-us/articles/4408889192858", "fields": [
        _f("subdomain", "Subdomain", store="config", placeholder="your-company", help="The part before .zendesk.com"),
        _f("email", "Agent email", store="credentials", placeholder="agent@company.com"),
        _f("api_token", "API token", store="credentials", secret=True, help="Admin Center → Apps and integrations → Zendesk API."),
    ]},
}

REQUIRED_CREDENTIALS: dict[tuple[str, str], list[str]] = {k: [f["key"] for f in spec["fields"] if f["store"] == "credentials" and f["required"]] for k, spec in CONNECTION_FIELDS.items()}


def build(family: str, live_provider: str, config: dict[str, Any], credentials: dict[str, Any]) -> BaseAdapter | None:
    cls = LIVE_ADAPTERS.get((family, live_provider))
    if cls is None:
        return None
    missing = [k for k in REQUIRED_CREDENTIALS.get((family, live_provider), []) if not credentials.get(k)]
    if missing:
        raise IntegrationNotConfigured(f"Missing credentials for {live_provider}: {', '.join(missing)}")
    return cls(config, credentials)  # type: ignore[call-arg]
