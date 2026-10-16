"""Mock adapters for every provider family.

They operate on the tenant's sandbox records (see `sandbox.py`) and therefore
behave like real systems: state persists, writes are visible to later reads,
duplicates are detectable, and outcomes can be verified. They never contact the
network. Every mock adapter reports `mode="mock"` so the dashboard and audit
trail can never confuse sandbox activity with a live integration.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import IntegrationError, NotFound
from app.integrations.base import BaseAdapter, ConnectionTestResult, VerificationResult
from app.integrations.sandbox import SandboxStore


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


class MockAdapter(BaseAdapter):
    mode = "mock"

    def __init__(self, db: Session, tenant_id: str) -> None:
        self.store = SandboxStore(db, tenant_id)
        self.tenant_id = tenant_id

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(
            ok=True,
            mode="mock",
            provider=self.provider,
            message="Sandbox adapter (no external system connected)",
            details={"capabilities": self.capabilities},
        )

    # Generic verification for sandbox writes: check the record exists.
    def verify_action(self, method: str, request: dict[str, Any], external_ref: str | None) -> VerificationResult | None:
        if not external_ref:
            return VerificationResult(verified=False, details={"reason": "no external reference"})
        for rt in self._verifiable_record_types():
            rec = self.store.get(rt, external_ref) or self.store.find_one(rt, idempotency_key=external_ref)
            if rec:
                return VerificationResult(verified=True, exists=True, external_ref=rec.get("id", external_ref), details={"record_type": rt})
        return VerificationResult(verified=True, exists=False, external_ref=external_ref)

    def _verifiable_record_types(self) -> list[str]:
        return []

    def _outbox(self, channel: str, payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        """All outbound communications land in the sandbox outbox (never sent anywhere)."""
        if idempotency_key:
            existing = self.store.find_one("outbox", idempotency_key=idempotency_key)
            if existing:
                return {**existing, "duplicate_suppressed": True}
        rec = self.store.append(
            "outbox",
            {
                "channel": channel,
                "idempotency_key": idempotency_key,
                "sent_at": _iso(_now()),
                "status": "sent_sandbox",
                **payload,
            },
            prefix="MSG",
        )
        return rec


# ---------------------------------------------------------------------------
# CRM
# ---------------------------------------------------------------------------


class MockCRMAdapter(MockAdapter):
    provider = "crm"
    display_name = "CRM (sandbox)"
    capabilities = ["leads", "contacts", "activities", "customers", "consent"]

    def _verifiable_record_types(self) -> list[str]:
        return ["lead", "activity", "customer", "followup", "consent"]

    def find_lead(self, email: str | None = None, phone: str | None = None, company: str | None = None) -> dict[str, Any]:
        matches: list[dict[str, Any]] = []
        for lead in self.store.list("lead"):
            if email and (lead.get("email") or "").lower() == email.lower():
                matches.append(lead)
            elif phone and _norm_phone(lead.get("phone")) == _norm_phone(phone) and _norm_phone(phone):
                matches.append(lead)
            elif company and (lead.get("company") or "").strip().lower() == company.strip().lower() and not email:
                matches.append(lead)
        return {"matches": matches, "count": len(matches)}

    def list_leads(self, status: str | None = None, limit: int = 100) -> dict[str, Any]:
        leads = self.store.list("lead", limit=limit, status=status)
        return {"items": leads, "count": len(leads)}

    def get_lead(self, lead_id: str) -> dict[str, Any]:
        lead = self.store.get("lead", lead_id)
        if not lead:
            raise NotFound(f"Lead {lead_id} not found")
        return lead

    def upsert_lead(self, lead: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        lead_id = lead.get("id") or f"L-{uuid.uuid4().hex[:6].upper()}"
        rec = self.store.upsert("lead", lead_id, lead, status=lead.get("status"))
        return {"lead": rec, "id": lead_id}

    def update_lead(self, lead_id: str, fields: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        rec = self.store.update("lead", lead_id, fields)
        if rec is None:
            raise NotFound(f"Lead {lead_id} not found")
        return {"lead": rec, "id": lead_id}

    def log_activity(self, lead_id: str, activity_type: str, note: str, idempotency_key: str | None = None) -> dict[str, Any]:
        if idempotency_key:
            existing = self.store.find_one("activity", idempotency_key=idempotency_key)
            if existing:
                return {"activity": existing, "id": existing["id"], "duplicate_suppressed": True}
        rec = self.store.append(
            "activity",
            {"lead_id": lead_id, "type": activity_type, "note": note, "at": _iso(_now()), "idempotency_key": idempotency_key},
            prefix="ACT",
        )
        return {"activity": rec, "id": rec["id"]}

    def get_activity(self, lead_id: str) -> dict[str, Any]:
        items = self.store.list("activity", lead_id=lead_id)
        return {"items": items, "count": len(items)}

    def schedule_followup(self, lead_id: str, at: str, note: str, idempotency_key: str | None = None) -> dict[str, Any]:
        if idempotency_key:
            existing = self.store.find_one("followup", idempotency_key=idempotency_key)
            if existing:
                return {"followup": existing, "id": existing["id"], "duplicate_suppressed": True}
        rec = self.store.append(
            "followup", {"lead_id": lead_id, "at": at, "note": note, "status": "scheduled", "idempotency_key": idempotency_key}, prefix="FU"
        )
        return {"followup": rec, "id": rec["id"]}

    def list_customers(self, segment: str | None = None, limit: int = 500) -> dict[str, Any]:
        items = self.store.list("customer", limit=limit, segment=segment)
        return {"items": items, "count": len(items)}

    def get_customer(self, customer_id: str) -> dict[str, Any]:
        c = self.store.get("customer", customer_id)
        if not c:
            raise NotFound(f"Customer {customer_id} not found")
        return c

    def check_consent(self, email: str | None = None, phone: str | None = None) -> dict[str, Any]:
        for rec in self.store.list("consent"):
            if (email and (rec.get("email") or "").lower() == email.lower()) or (
                phone and _norm_phone(rec.get("phone")) == _norm_phone(phone) and _norm_phone(phone)
            ):
                return {
                    "found": True,
                    "marketing_opt_in": bool(rec.get("marketing_opt_in")),
                    "unsubscribed": bool(rec.get("unsubscribed")),
                    "channels": rec.get("channels", []),
                    "do_not_contact": bool(rec.get("do_not_contact")),
                }
        return {"found": False, "marketing_opt_in": False, "unsubscribed": False, "channels": [], "do_not_contact": False}

    def get_sales_teams(self) -> dict[str, Any]:
        return {"items": self.store.list("sales_team")}

    def get_price_list(self) -> dict[str, Any]:
        return {"items": self.store.list("price_item")}

    def get_proposal_templates(self) -> dict[str, Any]:
        return {"items": self.store.list("proposal_template")}

    def update_consent(self, email: str | None = None, phone: str | None = None, unsubscribed: bool = True, channel: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        rec = None
        for c in self.store.list("consent"):
            if (email and (c.get("email") or "").lower() == email.lower()) or (phone and _norm_phone(c.get("phone")) == _norm_phone(phone) and _norm_phone(phone)):
                rec = c
                break
        fields = {"unsubscribed": unsubscribed, "marketing_opt_in": not unsubscribed, "whatsapp_opt_in": not unsubscribed, "updated_via": channel}
        if rec:
            updated = self.store.update("consent", rec["id"], fields)
            return {"id": rec["id"], "consent": updated}
        new = self.store.append("consent", {"email": email, "phone": phone, **fields}, prefix="CON")
        return {"id": new["id"], "consent": new}


def _norm_phone(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())[-10:]


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


class MockEmailAdapter(MockAdapter):
    provider = "email"
    display_name = "Email (sandbox outbox)"
    capabilities = ["send", "templates", "outbox"]

    def _verifiable_record_types(self) -> list[str]:
        return ["outbox"]

    def send(self, to: str, subject: str, body: str, template_id: str | None = None, idempotency_key: str | None = None, **meta: Any) -> dict[str, Any]:
        if "@" not in to:
            raise IntegrationError("Invalid recipient address")
        rec = self._outbox("email", {"to": to, "subject": subject, "body": body, "template_id": template_id, **meta}, idempotency_key)
        return {"message_id": rec["id"], "status": rec["status"], "duplicate_suppressed": rec.get("duplicate_suppressed", False)}

    def list_templates(self, category: str | None = None) -> dict[str, Any]:
        return {"items": self.store.list("email_template", category=category)}

    def list_outbox(self, limit: int = 50) -> dict[str, Any]:
        return {"items": self.store.list("outbox", limit=limit, channel="email")}


# ---------------------------------------------------------------------------
# Chat (Slack-like)
# ---------------------------------------------------------------------------


class MockChatAdapter(MockAdapter):
    provider = "chat"
    display_name = "Team chat (sandbox)"
    capabilities = ["post_message", "channels"]

    def _verifiable_record_types(self) -> list[str]:
        return ["outbox"]

    def post_message(self, channel: str, text: str, idempotency_key: str | None = None, **meta: Any) -> dict[str, Any]:
        rec = self._outbox("chat", {"channel_name": channel, "text": text, **meta}, idempotency_key)
        return {"message_id": rec["id"], "channel": channel, "status": rec["status"], "duplicate_suppressed": rec.get("duplicate_suppressed", False)}

    def list_channels(self) -> dict[str, Any]:
        return {"items": self.store.list("chat_channel") or [{"id": "C-OPS", "name": "#ops"}, {"id": "C-SALES", "name": "#sales"}]}


# ---------------------------------------------------------------------------
# Task / issue tracker (Jira-like)
# ---------------------------------------------------------------------------


class MockIssueTrackerAdapter(MockAdapter):
    provider = "issues"
    display_name = "Issue tracker (sandbox)"
    capabilities = ["issues", "search", "comments", "projects"]

    def _verifiable_record_types(self) -> list[str]:
        return ["issue"]

    def search_issues(self, query: str = "", project: str | None = None, status: str | None = None, limit: int = 50) -> dict[str, Any]:
        q = (query or "").lower()
        items = []
        for issue in self.store.list("issue", limit=1000, project=project, status=status):
            text = f"{issue.get('title','')} {issue.get('description','')}".lower()
            if not q or q in text:
                items.append(issue)
        return {"items": items[:limit], "count": len(items[:limit])}

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        issue = self.store.get("issue", issue_key)
        if not issue:
            raise NotFound(f"Issue {issue_key} not found")
        return issue

    def create_issue(
        self,
        project: str,
        title: str,
        description: str = "",
        priority: str = "medium",
        issue_type: str = "task",
        assignee: str | None = None,
        labels: list[str] | None = None,
        idempotency_key: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        if idempotency_key:
            existing = self.store.find_one("issue", idempotency_key=idempotency_key)
            if existing:
                return {"issue": existing, "key": existing["id"], "duplicate_suppressed": True}
        seq = self.store.count("issue") + 1
        key = f"{project.upper()}-{seq}"
        rec = self.store.upsert(
            "issue",
            key,
            {
                "project": project.upper(),
                "title": title,
                "description": description,
                "priority": priority,
                "issue_type": issue_type,
                "assignee": assignee,
                "labels": labels or [],
                "status": "open",
                "created_at": _iso(_now()),
                "idempotency_key": idempotency_key,
                **extra,
            },
            status="open",
        )
        return {"issue": rec, "key": key, "duplicate_suppressed": False}

    def update_issue(self, issue_key: str, fields: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        rec = self.store.update("issue", issue_key, fields)
        if rec is None:
            raise NotFound(f"Issue {issue_key} not found")
        return {"issue": rec, "key": issue_key}

    def add_comment(self, issue_key: str, body: str, idempotency_key: str | None = None) -> dict[str, Any]:
        issue = self.get_issue(issue_key)
        comments = list(issue.get("comments", []))
        if idempotency_key and any(c.get("idempotency_key") == idempotency_key for c in comments):
            return {"issue": issue, "duplicate_suppressed": True}
        comments.append({"body": body, "at": _iso(_now()), "idempotency_key": idempotency_key})
        rec = self.store.update("issue", issue_key, {"comments": comments})
        return {"issue": rec, "key": issue_key, "duplicate_suppressed": False}

    def list_projects(self) -> dict[str, Any]:
        return {"items": self.store.list("project") or [{"id": "OPS", "name": "Operations"}, {"id": "ENG", "name": "Engineering"}]}


# ---------------------------------------------------------------------------
# Helpdesk / tickets
# ---------------------------------------------------------------------------


class MockHelpdeskAdapter(MockAdapter):
    provider = "helpdesk"
    display_name = "Helpdesk (sandbox)"
    capabilities = ["tickets", "case_history", "sla"]

    def _verifiable_record_types(self) -> list[str]:
        return ["ticket"]

    def list_tickets(self, customer_id: str | None = None, status: str | None = None, limit: int = 100) -> dict[str, Any]:
        items = self.store.list("ticket", limit=limit, customer_id=customer_id, status=status)
        return {"items": items, "count": len(items)}

    def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        t = self.store.get("ticket", ticket_id)
        if not t:
            raise NotFound(f"Ticket {ticket_id} not found")
        return t

    def get_case_history(self, customer_id: str) -> dict[str, Any]:
        items = self.store.list("ticket", customer_id=customer_id)
        return {"items": items, "count": len(items)}

    def create_ticket(
        self,
        subject: str,
        description: str,
        customer_id: str | None = None,
        category: str = "general",
        priority: str = "medium",
        sla_hours: int | None = None,
        idempotency_key: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        if idempotency_key:
            existing = self.store.find_one("ticket", idempotency_key=idempotency_key)
            if existing:
                return {"ticket": existing, "id": existing["id"], "duplicate_suppressed": True}
        due = _iso(_now() + timedelta(hours=sla_hours)) if sla_hours else None
        rec = self.store.append(
            "ticket",
            {
                "subject": subject,
                "description": description,
                "customer_id": customer_id,
                "category": category,
                "priority": priority,
                "status": "open",
                "sla_due_at": due,
                "created_at": _iso(_now()),
                "idempotency_key": idempotency_key,
                **extra,
            },
            prefix="TKT",
        )
        return {"ticket": rec, "id": rec["id"], "duplicate_suppressed": False}

    def update_ticket(self, ticket_id: str, fields: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        rec = self.store.update("ticket", ticket_id, fields)
        if rec is None:
            raise NotFound(f"Ticket {ticket_id} not found")
        return {"ticket": rec, "id": ticket_id}

    def get_policies(self, topic: str | None = None) -> dict[str, Any]:
        return {"items": self.store.list("support_policy", topic=topic)}


# ---------------------------------------------------------------------------
# Commerce (Shopify-like) + inventory + suppliers
# ---------------------------------------------------------------------------


class MockCommerceAdapter(MockAdapter):
    provider = "commerce"
    display_name = "Commerce platform (sandbox)"
    capabilities = ["products", "orders", "shipments", "inventory", "carts", "listings"]

    def _verifiable_record_types(self) -> list[str]:
        return ["cart", "product", "order", "purchase_order"]

    def search_products(self, query: str = "", category: str | None = None, max_price: float | None = None, limit: int = 10) -> dict[str, Any]:
        q = (query or "").lower()
        terms = [t for t in q.replace(",", " ").split() if len(t) > 2]
        scored: list[tuple[int, dict[str, Any]]] = []
        for p in self.store.list("product", limit=1000, category=category):
            if max_price is not None and float(p.get("price", 0)) > max_price:
                continue
            text = f"{p.get('title','')} {p.get('description','')} {' '.join(map(str, p.get('tags', [])))} {p.get('category','')}".lower()
            score = sum(1 for t in terms if t in text)
            if not terms or score:
                scored.append((score, p))
        scored.sort(key=lambda x: (-x[0], float(x[1].get("price", 0))))
        return {"items": [p for _, p in scored[:limit]], "count": len(scored)}

    def get_product(self, product_id: str) -> dict[str, Any]:
        p = self.store.get("product", product_id)
        if not p:
            raise NotFound(f"Product {product_id} not found")
        return p

    def get_price_and_stock(self, product_id: str) -> dict[str, Any]:
        p = self.get_product(product_id)
        return {
            "product_id": product_id,
            "price": p.get("price"),
            "currency": p.get("currency", "USD"),
            "stock": p.get("stock", 0),
            "in_stock": int(p.get("stock", 0)) > 0,
            "checked_at": _iso(_now()),
        }

    def get_delivery_policy(self) -> dict[str, Any]:
        pol = self.store.find_one("policy", key="delivery") or {
            "key": "delivery",
            "standard_days": "3-5",
            "express_days": "1-2",
            "free_shipping_threshold": 75,
            "returns_days": 30,
        }
        return pol

    def create_cart(self, items: list[dict[str, Any]], customer_id: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        if idempotency_key:
            existing = self.store.find_one("cart", idempotency_key=idempotency_key)
            if existing:
                return {"cart": existing, "id": existing["id"], "duplicate_suppressed": True}
        total = 0.0
        lines = []
        for it in items:
            p = self.get_product(it["product_id"])
            qty = int(it.get("quantity", 1))
            line_total = round(float(p["price"]) * qty, 2)
            total += line_total
            lines.append({"product_id": p["id"], "title": p["title"], "quantity": qty, "unit_price": p["price"], "line_total": line_total})
        rec = self.store.append(
            "cart",
            {"customer_id": customer_id, "lines": lines, "total": round(total, 2), "status": "draft", "idempotency_key": idempotency_key, "created_at": _iso(_now())},
            prefix="CART",
        )
        return {"cart": rec, "id": rec["id"], "duplicate_suppressed": False}

    def list_orders(self, status: str | None = None, since_days: int | None = None, limit: int = 200) -> dict[str, Any]:
        items = self.store.list("order", limit=limit, status=status)
        if since_days:
            cutoff = _now() - timedelta(days=since_days)
            items = [o for o in items if (_parse_dt(o.get("created_at")) or _now()) >= cutoff]
        return {"items": items, "count": len(items)}

    def get_order(self, order_id: str) -> dict[str, Any]:
        o = self.store.get("order", order_id)
        if not o:
            raise NotFound(f"Order {order_id} not found")
        return o

    def get_shipment(self, order_id: str) -> dict[str, Any]:
        s = self.store.find_one("shipment", order_id=order_id)
        if not s:
            return {"order_id": order_id, "found": False}
        return {"found": True, **s}

    def update_order(self, order_id: str, fields: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        rec = self.store.update("order", order_id, fields)
        if rec is None:
            raise NotFound(f"Order {order_id} not found")
        return {"order": rec, "id": order_id}

    def get_inventory(self, sku: str) -> dict[str, Any]:
        inv = self.store.find_one("inventory", sku=sku)
        if not inv:
            raise NotFound(f"No inventory record for SKU {sku}")
        return inv

    def list_inventory(self, limit: int = 500) -> dict[str, Any]:
        return {"items": self.store.list("inventory", limit=limit)}

    def get_sales_history(self, sku: str, days: int = 90) -> dict[str, Any]:
        hist = self.store.find_one("sales_history", sku=sku)
        if not hist:
            return {"sku": sku, "daily_units": [], "days": 0}
        series = list(hist.get("daily_units", []))[-days:]
        return {"sku": sku, "daily_units": series, "days": len(series)}

    def get_supplier_lead_time(self, sku: str) -> dict[str, Any]:
        inv = self.store.find_one("inventory", sku=sku) or {}
        return {"sku": sku, "lead_time_days": inv.get("lead_time_days"), "supplier_id": inv.get("supplier_id")}

    def update_listing(self, product_id: str, fields: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        rec = self.store.update("product", product_id, fields)
        if rec is None:
            raise NotFound(f"Product {product_id} not found")
        return {"product": rec, "id": product_id}

    def create_purchase_order(self, supplier_id: str, lines: list[dict[str, Any]], idempotency_key: str | None = None, **extra: Any) -> dict[str, Any]:
        if idempotency_key:
            existing = self.store.find_one("purchase_order", idempotency_key=idempotency_key)
            if existing:
                return {"purchase_order": existing, "id": existing["id"], "duplicate_suppressed": True}
        total = round(sum(float(line.get("unit_cost", 0)) * int(line.get("quantity", 0)) for line in lines), 2)
        rec = self.store.append(
            "purchase_order",
            {"supplier_id": supplier_id, "lines": lines, "total": total, "status": "issued", "idempotency_key": idempotency_key, "created_at": _iso(_now()), **extra},
            prefix="PO",
        )
        return {"purchase_order": rec, "id": rec["id"], "duplicate_suppressed": False}

    def get_brand_guidelines(self) -> dict[str, Any]:
        return self.store.find_one("policy", key="brand_guidelines") or {
            "key": "brand_guidelines",
            "tone": "clear, confident, friendly",
            "prohibited_claims": ["cures", "guaranteed", "100% safe", "best in the world", "clinically proven"],
            "required_fields": ["title", "description", "specifications"],
        }


# ---------------------------------------------------------------------------
# Accounting / finance / expenses
# ---------------------------------------------------------------------------


class MockAccountingAdapter(MockAdapter):
    provider = "accounting"
    display_name = "Accounting (sandbox)"
    capabilities = ["invoices", "purchase_orders", "receipts", "expenses", "payables", "reminders"]

    def _verifiable_record_types(self) -> list[str]:
        return ["payable", "followup", "invoice"]

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        inv = self.store.get("invoice", invoice_id)
        if not inv:
            raise NotFound(f"Invoice {invoice_id} not found")
        return inv

    def list_invoices(self, status: str | None = None, overdue_only: bool = False, limit: int = 200) -> dict[str, Any]:
        items = self.store.list("invoice", limit=limit, status=status)
        if overdue_only:
            now = _now()
            items = [i for i in items if (_parse_dt(i.get("due_date")) or now) < now and i.get("status") not in {"paid", "void"}]
        return {"items": items, "count": len(items)}

    def find_invoices(self, vendor: str | None = None, invoice_number: str | None = None, amount: float | None = None) -> dict[str, Any]:
        items = []
        for inv in self.store.list("invoice", limit=1000):
            if vendor and (inv.get("vendor") or "").lower() != vendor.lower():
                continue
            if invoice_number and (inv.get("invoice_number") or "") != invoice_number:
                continue
            if amount is not None and abs(float(inv.get("total", 0)) - amount) > 0.005:
                continue
            items.append(inv)
        return {"items": items, "count": len(items)}

    def get_purchase_order(self, po_number: str) -> dict[str, Any]:
        po = self.store.get("purchase_order", po_number)
        if not po:
            raise NotFound(f"Purchase order {po_number} not found")
        return po

    def list_purchase_orders(self, vendor: str | None = None, status: str | None = None) -> dict[str, Any]:
        items = self.store.list("purchase_order", status=status)
        if vendor:
            items = [p for p in items if (p.get("vendor") or p.get("supplier_id") or "").lower() == vendor.lower()]
        return {"items": items, "count": len(items)}

    def list_receipts(self, po_number: str | None = None) -> dict[str, Any]:
        items = self.store.list("goods_receipt", po_number=po_number)
        return {"items": items, "count": len(items)}

    def create_payable(self, invoice: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        if idempotency_key:
            existing = self.store.find_one("payable", idempotency_key=idempotency_key)
            if existing:
                return {"payable": existing, "id": existing["id"], "duplicate_suppressed": True}
        rec = self.store.append(
            "payable",
            {**invoice, "status": "pending_approval", "idempotency_key": idempotency_key, "created_at": _iso(_now())},
            prefix="AP",
        )
        return {"payable": rec, "id": rec["id"], "duplicate_suppressed": False}

    def list_expense_claims(self, status: str | None = None, employee_id: str | None = None, limit: int = 500) -> dict[str, Any]:
        items = self.store.list("expense_claim", limit=limit, status=status, employee_id=employee_id)
        return {"items": items, "count": len(items)}

    def get_expense_claim(self, claim_id: str) -> dict[str, Any]:
        c = self.store.get("expense_claim", claim_id)
        if not c:
            raise NotFound(f"Expense claim {claim_id} not found")
        return c

    def get_expense_policy(self) -> dict[str, Any]:
        return self.store.find_one("policy", key="expense") or {
            "key": "expense",
            "receipt_required_above": 25,
            "category_limits": {"meals": 75, "travel": 500, "lodging": 250, "equipment": 1000, "other": 100},
            "duplicate_window_days": 7,
            "prohibited_categories": ["personal", "alcohol"],
        }

    def flag_expense(self, claim_id: str, flags: list[dict[str, Any]], idempotency_key: str | None = None) -> dict[str, Any]:
        rec = self.store.update("expense_claim", claim_id, {"status": "flagged", "flags": flags, "flagged_at": _iso(_now())})
        if rec is None:
            raise NotFound(f"Expense claim {claim_id} not found")
        return {"claim": rec, "id": claim_id}

    def get_followup_history(self, invoice_id: str) -> dict[str, Any]:
        items = self.store.list("followup", invoice_id=invoice_id)
        return {"items": items, "count": len(items)}

    def record_followup(self, invoice_id: str, channel: str, note: str, stage: str, idempotency_key: str | None = None) -> dict[str, Any]:
        if idempotency_key:
            existing = self.store.find_one("followup", idempotency_key=idempotency_key)
            if existing:
                return {"followup": existing, "id": existing["id"], "duplicate_suppressed": True}
        rec = self.store.append(
            "followup",
            {"invoice_id": invoice_id, "channel": channel, "note": note, "stage": stage, "at": _iso(_now()), "idempotency_key": idempotency_key},
            prefix="FU",
        )
        return {"followup": rec, "id": rec["id"], "duplicate_suppressed": False}

    def get_cost_ledger(self, months: int = 3) -> dict[str, Any]:
        return {"items": self.store.list("cost_ledger")[-(months * 40) :]}

    def get_revenue(self, months: int = 3) -> dict[str, Any]:
        return {"items": self.store.list("revenue")[-(months * 40) :]}

    def get_budgets(self) -> dict[str, Any]:
        return {"items": self.store.list("budget")}


# ---------------------------------------------------------------------------
# WhatsApp Business (sandbox)
# ---------------------------------------------------------------------------


class MockWhatsAppAdapter(MockAdapter):
    provider = "whatsapp"
    display_name = "WhatsApp Business (sandbox)"
    capabilities = ["send_template", "send_text", "opt_in", "templates", "webhooks"]

    def _verifiable_record_types(self) -> list[str]:
        return ["outbox"]

    def check_opt_in(self, phone: str) -> dict[str, Any]:
        rec = next((c for c in self.store.list("consent") if _norm_phone(c.get("phone")) == _norm_phone(phone) and _norm_phone(phone)), None)
        if not rec:
            return {"found": False, "opted_in": False}
        return {"found": True, "opted_in": bool(rec.get("whatsapp_opt_in", rec.get("marketing_opt_in"))), "last_inbound_at": rec.get("last_inbound_at")}

    def list_templates(self) -> dict[str, Any]:
        return {"items": self.store.list("whatsapp_template")}

    def send_template(self, to: str, template_name: str, parameters: list[str] | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        templates = {t["name"]: t for t in self.store.list("whatsapp_template")}
        if templates and template_name not in templates:
            raise IntegrationError(f"Template '{template_name}' is not approved", details={"available": list(templates)})
        rec = self._outbox("whatsapp", {"to": to, "template": template_name, "parameters": parameters or []}, idempotency_key)
        return {"message_id": rec["id"], "status": rec["status"], "duplicate_suppressed": rec.get("duplicate_suppressed", False)}

    def _last_inbound(self, phone: str) -> datetime | None:
        inbound = [m for m in self.store.list("whatsapp_message", limit=5000) if _norm_phone(m.get("phone")) == _norm_phone(phone) and m.get("direction") == "inbound"]
        times = [t for t in (_parse_dt(m.get("at")) for m in inbound) if t]
        consent = self.check_opt_in(phone)
        c_time = _parse_dt(consent.get("last_inbound_at"))
        if c_time:
            times.append(c_time)
        return max(times) if times else None

    def send_text(self, to: str, text: str, idempotency_key: str | None = None) -> dict[str, Any]:
        last = self._last_inbound(to)
        if not last or (_now() - last) > timedelta(hours=24):
            raise IntegrationError("Free-form messages are only allowed within 24h of the customer's last inbound message; use a template")
        rec = self._outbox("whatsapp", {"to": to, "text": text}, idempotency_key)
        if not rec.get("duplicate_suppressed"):
            self.store.append("whatsapp_message", {"phone": to, "direction": "outbound", "text": text, "at": _iso(_now())}, prefix="WAM")
        return {"message_id": rec["id"], "status": rec["status"], "duplicate_suppressed": rec.get("duplicate_suppressed", False)}

    def get_conversation(self, phone: str, limit: int = 20) -> dict[str, Any]:
        items = [m for m in self.store.list("whatsapp_message", limit=1000) if _norm_phone(m.get("phone")) == _norm_phone(phone)]
        return {"items": items[-limit:], "count": len(items)}


# ---------------------------------------------------------------------------
# Workspace (directory, calendar, docs, meetings)
# ---------------------------------------------------------------------------


class MockWorkspaceAdapter(MockAdapter):
    provider = "workspace"
    display_name = "Workspace directory & calendar (sandbox)"
    capabilities = ["directory", "calendar", "meetings", "documents"]

    def _verifiable_record_types(self) -> list[str]:
        return ["calendar_event"]

    def list_employees(self, department: str | None = None) -> dict[str, Any]:
        return {"items": self.store.list("employee", department=department)}

    def directory_lookup(self, name: str | None = None, email: str | None = None) -> dict[str, Any]:
        from rapidfuzz import fuzz

        employees = self.store.list("employee")
        if email:
            matches = [e for e in employees if (e.get("email") or "").lower() == email.lower()]
            return {"matches": matches, "ambiguous": False, "query": email}
        if not name:
            return {"matches": [], "ambiguous": False, "query": None}
        q = name.strip().lower()
        scored = []
        for e in employees:
            full = (e.get("name") or "").lower()
            first = full.split(" ")[0] if full else ""
            score = max(fuzz.ratio(q, full), fuzz.ratio(q, first) if len(q) >= 3 else 0, 100 if q == first else 0)
            if score >= 80:
                scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        matches = [e for _, e in scored]
        ambiguous = len(matches) > 1 and scored[0][0] - scored[1][0] < 10
        return {"matches": matches, "ambiguous": ambiguous, "query": name}

    def get_transcript(self, meeting_id: str) -> dict[str, Any]:
        m = self.store.get("meeting", meeting_id)
        if not m:
            raise NotFound(f"Meeting {meeting_id} not found")
        return m

    def create_calendar_event(self, title: str, start: str, end: str, attendees: list[str] | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        if idempotency_key:
            existing = self.store.find_one("calendar_event", idempotency_key=idempotency_key)
            if existing:
                return {"event": existing, "id": existing["id"], "duplicate_suppressed": True}
        rec = self.store.append("calendar_event", {"title": title, "start": start, "end": end, "attendees": attendees or [], "idempotency_key": idempotency_key}, prefix="EVT")
        return {"event": rec, "id": rec["id"], "duplicate_suppressed": False}


# ---------------------------------------------------------------------------
# Monitoring / telemetry
# ---------------------------------------------------------------------------


class MockMonitoringAdapter(MockAdapter):
    provider = "monitoring"
    display_name = "Monitoring & deployments (sandbox)"
    capabilities = ["deployments", "metrics", "logs", "alerts"]

    def _verifiable_record_types(self) -> list[str]:
        return ["alert"]

    def get_deployments(self, service: str | None = None, limit: int = 20) -> dict[str, Any]:
        items = self.store.list("deployment", limit=limit, service=service)
        return {"items": items, "count": len(items)}

    def get_metrics(self, service: str, window_minutes: int = 60) -> dict[str, Any]:
        series = self.store.find_one("telemetry", service=service)
        if not series:
            return {"service": service, "found": False, "points": []}
        points = list(series.get("points", []))[-window_minutes:]
        return {"service": service, "found": True, "points": points, "thresholds": series.get("thresholds", {})}

    def get_logs(self, service: str, level: str = "error", limit: int = 50) -> dict[str, Any]:
        items = [e for e in self.store.list("log_entry", limit=5000, service=service) if (e.get("level") or "").lower() == level.lower()]
        return {"items": items[-limit:], "count": len(items)}

    def create_alert(self, title: str, severity: str, body: str, service: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        if idempotency_key:
            existing = self.store.find_one("alert", idempotency_key=idempotency_key)
            if existing:
                return {"alert": existing, "id": existing["id"], "duplicate_suppressed": True}
        rec = self.store.append("alert", {"title": title, "severity": severity, "body": body, "service": service, "status": "open", "created_at": _iso(_now()), "idempotency_key": idempotency_key}, prefix="ALR")
        return {"alert": rec, "id": rec["id"], "duplicate_suppressed": False}

    def get_test_environments(self) -> dict[str, Any]:
        return {"items": self.store.list("test_environment")}


# ---------------------------------------------------------------------------
# Procurement
# ---------------------------------------------------------------------------


class MockProcurementAdapter(MockAdapter):
    provider = "procurement"
    display_name = "Procurement (sandbox)"
    capabilities = ["rfqs", "quotes", "suppliers", "policies", "purchase_orders"]

    def _verifiable_record_types(self) -> list[str]:
        return ["purchase_order"]

    def get_rfq(self, rfq_id: str) -> dict[str, Any]:
        r = self.store.get("rfq", rfq_id)
        if not r:
            raise NotFound(f"RFQ {rfq_id} not found")
        return r

    def list_quotes(self, rfq_id: str) -> dict[str, Any]:
        items = self.store.list("quote", rfq_id=rfq_id)
        return {"items": items, "count": len(items)}

    def get_supplier(self, supplier_id: str) -> dict[str, Any]:
        s = self.store.get("supplier", supplier_id)
        if not s:
            raise NotFound(f"Supplier {supplier_id} not found")
        return s

    def list_suppliers(self) -> dict[str, Any]:
        return {"items": self.store.list("supplier")}

    def get_policy(self) -> dict[str, Any]:
        return self.store.find_one("policy", key="procurement") or {
            "key": "procurement",
            "min_quotes": 3,
            "approved_suppliers_only": True,
            "max_single_approval": 10000,
            "required_fields": ["unit_price", "lead_time_days", "payment_terms", "warranty_months"],
        }

    def create_purchase_order(self, supplier_id: str, rfq_id: str, lines: list[dict[str, Any]], total: float, idempotency_key: str | None = None) -> dict[str, Any]:
        if idempotency_key:
            existing = self.store.find_one("purchase_order", idempotency_key=idempotency_key)
            if existing:
                return {"purchase_order": existing, "id": existing["id"], "duplicate_suppressed": True}
        rec = self.store.append("purchase_order", {"supplier_id": supplier_id, "rfq_id": rfq_id, "lines": lines, "total": total, "status": "issued", "created_at": _iso(_now()), "idempotency_key": idempotency_key}, prefix="PO")
        return {"purchase_order": rec, "id": rec["id"], "duplicate_suppressed": False}


# ---------------------------------------------------------------------------
# Product feedback sources
# ---------------------------------------------------------------------------


class MockFeedbackAdapter(MockAdapter):
    provider = "feedback"
    display_name = "Customer feedback sources (sandbox)"
    capabilities = ["feedback", "reviews", "feature_requests"]

    def list_feedback(self, source: str | None = None, since_days: int | None = None, limit: int = 1000) -> dict[str, Any]:
        items = self.store.list("feedback", limit=limit, source=source)
        if since_days:
            cutoff = _now() - timedelta(days=since_days)
            items = [f for f in items if (_parse_dt(f.get("created_at")) or _now()) >= cutoff]
        return {"items": items, "count": len(items)}


# ---------------------------------------------------------------------------
# Business metrics (platform-internal metric series)
# ---------------------------------------------------------------------------


class MockMetricsAdapter(MockAdapter):
    provider = "metrics"
    display_name = "Business metrics warehouse (sandbox)"
    capabilities = ["metric_series", "sop_records", "workflow_records"]

    def list_metrics(self) -> dict[str, Any]:
        return {"items": [{"key": m["key"], "label": m.get("label"), "unit": m.get("unit")} for m in self.store.list("metric_series")]}

    def query_metric(self, metric_key: str, days: int = 30) -> dict[str, Any]:
        m = self.store.find_one("metric_series", key=metric_key)
        if not m:
            raise NotFound(f"Metric {metric_key} not found")
        points = list(m.get("points", []))[-days:]
        return {"key": metric_key, "label": m.get("label"), "unit": m.get("unit"), "points": points, "quality": m.get("quality", {})}

    def list_sops(self, process: str | None = None) -> dict[str, Any]:
        return {"items": self.store.list("sop", process=process)}

    def list_operational_records(self, process: str | None = None, limit: int = 500) -> dict[str, Any]:
        return {"items": self.store.list("operational_record", limit=limit, process=process)}


MOCK_ADAPTERS: dict[str, type[MockAdapter]] = {
    cls.provider: cls
    for cls in [
        MockCRMAdapter,
        MockEmailAdapter,
        MockChatAdapter,
        MockIssueTrackerAdapter,
        MockHelpdeskAdapter,
        MockCommerceAdapter,
        MockAccountingAdapter,
        MockWhatsAppAdapter,
        MockWorkspaceAdapter,
        MockMonitoringAdapter,
        MockProcurementAdapter,
        MockFeedbackAdapter,
        MockMetricsAdapter,
    ]
}

PROVIDER_FAMILIES: dict[str, dict[str, Any]] = {
    "crm": {"label": "CRM", "live_providers": ["hubspot"], "icon": "users"},
    "email": {"label": "Email", "live_providers": ["sendgrid", "smtp"], "icon": "mail"},
    "chat": {"label": "Team chat", "live_providers": ["slack"], "icon": "message-square"},
    "issues": {"label": "Issue tracker", "live_providers": ["jira"], "icon": "kanban"},
    "helpdesk": {"label": "Helpdesk", "live_providers": ["zendesk"], "icon": "life-buoy"},
    "commerce": {"label": "Commerce", "live_providers": ["shopify"], "icon": "shopping-bag"},
    "accounting": {"label": "Accounting", "live_providers": ["quickbooks", "xero"], "icon": "receipt"},
    "whatsapp": {"label": "WhatsApp Business", "live_providers": ["meta_cloud_api"], "icon": "phone"},
    "workspace": {"label": "Google Workspace", "live_providers": ["google_workspace"], "icon": "calendar"},
    "monitoring": {"label": "Monitoring", "live_providers": ["datadog", "grafana"], "icon": "activity"},
    "procurement": {"label": "Procurement", "live_providers": [], "icon": "package"},
    "feedback": {"label": "Feedback sources", "live_providers": [], "icon": "star"},
    "metrics": {"label": "Metrics warehouse", "live_providers": [], "icon": "bar-chart"},
}

