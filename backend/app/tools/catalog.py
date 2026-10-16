"""Registered tools. Importing this module populates the global tool registry.

Read-only tools (side_effect=False) may be called by agents directly through the
scoped ToolInvoker. Side-effecting tools can only be executed by the
ActionService after policy evaluation / human approval.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.tools.registry import tool


class _Flexible(BaseModel):
    model_config = ConfigDict(extra="allow")


# ---- CRM -------------------------------------------------------------------
class LeadLookup(_Flexible):
    email: str | None = None
    phone: str | None = None
    company: str | None = None


class LeadUpsert(_Flexible):
    lead: dict[str, Any]
    idempotency_key: str | None = None


class LeadUpdate(_Flexible):
    lead_id: str
    fields: dict[str, Any]
    idempotency_key: str | None = None


class ActivityLog(_Flexible):
    lead_id: str
    activity_type: str
    note: str
    idempotency_key: str | None = None


class FollowupSchedule(_Flexible):
    lead_id: str
    at: str
    note: str
    idempotency_key: str | None = None


tool(key="crm.find_lead", name="Find lead", description="Look up CRM leads by email, phone or company", provider="crm", method="find_lead", required_permission="crm:read", input_model=LeadLookup)
tool(key="crm.list_leads", name="List leads", description="List CRM leads", provider="crm", method="list_leads", required_permission="crm:read")
tool(key="crm.get_lead", name="Get lead", description="Fetch one CRM lead", provider="crm", method="get_lead", required_permission="crm:read")
tool(key="crm.get_activity", name="Lead activity", description="Fetch activity history for a lead", provider="crm", method="get_activity", required_permission="crm:read")
tool(key="crm.list_customers", name="List customers", description="List customers with usage and engagement data", provider="crm", method="list_customers", required_permission="crm:read")
tool(key="crm.get_customer", name="Get customer", description="Fetch a customer account", provider="crm", method="get_customer", required_permission="crm:read")
tool(key="crm.check_consent", name="Check consent", description="Check marketing consent / unsubscribe status", provider="crm", method="check_consent", required_permission="crm:read")
tool(key="crm.get_sales_teams", name="Sales teams", description="List sales teams and routing rules", provider="crm", method="get_sales_teams", required_permission="crm:read")
tool(key="crm.get_price_list", name="Price list", description="Approved pricing catalog with discount limits", provider="crm", method="get_price_list", required_permission="crm:read")
tool(key="crm.get_proposal_templates", name="Proposal templates", description="Approved proposal templates and standard terms", provider="crm", method="get_proposal_templates", required_permission="crm:read")


class ConsentUpdate(_Flexible):
    email: str | None = None
    phone: str | None = None
    unsubscribed: bool = True
    channel: str | None = None
    idempotency_key: str | None = None


tool(key="crm.update_consent", name="Update consent", description="Record an opt-out / consent change", provider="crm", method="update_consent", side_effect=True, required_permission="crm:write", risk_level="low", input_model=ConsentUpdate, external_ref_field="id")
tool(key="crm.upsert_lead", name="Upsert lead", description="Create or update a CRM lead", provider="crm", method="upsert_lead", side_effect=True, required_permission="crm:write", risk_level="low", input_model=LeadUpsert, external_ref_field="id")
tool(key="crm.update_lead", name="Update lead", description="Update fields on a CRM lead", provider="crm", method="update_lead", side_effect=True, required_permission="crm:write", risk_level="low", input_model=LeadUpdate, external_ref_field="id")
tool(key="crm.log_activity", name="Log activity", description="Record an activity note on a lead", provider="crm", method="log_activity", side_effect=True, required_permission="crm:write", risk_level="low", input_model=ActivityLog, external_ref_field="id")
tool(key="crm.schedule_followup", name="Schedule follow-up", description="Schedule a follow-up reminder", provider="crm", method="schedule_followup", side_effect=True, required_permission="crm:write", risk_level="low", input_model=FollowupSchedule, external_ref_field="id")


# ---- Email -----------------------------------------------------------------
class EmailSend(_Flexible):
    to: str
    subject: str
    body: str
    template_id: str | None = None
    idempotency_key: str | None = None


tool(key="email.list_templates", name="Email templates", description="List approved email templates", provider="email", method="list_templates", required_permission="email:read")
tool(key="email.list_outbox", name="Email outbox", description="List sent messages (sandbox outbox)", provider="email", method="list_outbox", required_permission="email:read")
tool(key="email.send", name="Send email", description="Send an external email", provider="email", method="send", side_effect=True, idempotent=False, required_permission="email:send", risk_level="high", input_model=EmailSend, external_ref_field="message_id")

# ---- Chat ------------------------------------------------------------------
class ChatPost(_Flexible):
    channel: str
    text: str
    idempotency_key: str | None = None


tool(key="chat.list_channels", name="List channels", description="List team chat channels", provider="chat", method="list_channels", required_permission="chat:read")
tool(key="chat.post_message", name="Post chat message", description="Post an internal chat notification", provider="chat", method="post_message", side_effect=True, idempotent=False, required_permission="chat:write", risk_level="low", input_model=ChatPost, external_ref_field="message_id")

# ---- Issues ----------------------------------------------------------------
class IssueCreate(_Flexible):
    project: str
    title: str
    description: str = ""
    priority: str = "medium"
    issue_type: str = "task"
    assignee: str | None = None
    labels: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None


class IssueUpdate(_Flexible):
    issue_key: str
    fields: dict[str, Any]
    idempotency_key: str | None = None


class IssueComment(_Flexible):
    issue_key: str
    body: str
    idempotency_key: str | None = None


tool(key="issues.search", name="Search issues", description="Search the issue tracker", provider="issues", method="search_issues", required_permission="issues:read")
tool(key="issues.get", name="Get issue", description="Fetch one issue", provider="issues", method="get_issue", required_permission="issues:read")
tool(key="issues.list_projects", name="List projects", description="List issue tracker projects", provider="issues", method="list_projects", required_permission="issues:read")
tool(key="issues.create", name="Create issue", description="Create an issue/task in the tracker", provider="issues", method="create_issue", side_effect=True, required_permission="issues:write", risk_level="medium", input_model=IssueCreate, external_ref_field="key")
tool(key="issues.update", name="Update issue", description="Update an issue", provider="issues", method="update_issue", side_effect=True, required_permission="issues:write", risk_level="low", input_model=IssueUpdate, external_ref_field="key")
tool(key="issues.comment", name="Comment on issue", description="Add a comment to an issue", provider="issues", method="add_comment", side_effect=True, required_permission="issues:write", risk_level="low", input_model=IssueComment, external_ref_field="key")

# ---- Helpdesk --------------------------------------------------------------
class TicketCreate(_Flexible):
    subject: str
    description: str
    customer_id: str | None = None
    category: str = "general"
    priority: str = "medium"
    sla_hours: int | None = None
    idempotency_key: str | None = None


class TicketUpdate(_Flexible):
    ticket_id: str
    fields: dict[str, Any]
    idempotency_key: str | None = None


tool(key="helpdesk.list_tickets", name="List tickets", description="List support tickets", provider="helpdesk", method="list_tickets", required_permission="helpdesk:read")
tool(key="helpdesk.get_ticket", name="Get ticket", description="Fetch a support ticket", provider="helpdesk", method="get_ticket", required_permission="helpdesk:read")
tool(key="helpdesk.case_history", name="Case history", description="Fetch a customer's case history", provider="helpdesk", method="get_case_history", required_permission="helpdesk:read")
tool(key="helpdesk.get_policies", name="Support policies", description="Fetch refund/compensation/escalation policies", provider="helpdesk", method="get_policies", required_permission="helpdesk:read")
tool(key="helpdesk.create_ticket", name="Create ticket", description="Create a support ticket", provider="helpdesk", method="create_ticket", side_effect=True, required_permission="helpdesk:write", risk_level="low", input_model=TicketCreate, external_ref_field="id")
tool(key="helpdesk.update_ticket", name="Update ticket", description="Update a support ticket", provider="helpdesk", method="update_ticket", side_effect=True, required_permission="helpdesk:write", risk_level="low", input_model=TicketUpdate, external_ref_field="id")

# ---- Commerce --------------------------------------------------------------
class CartCreate(_Flexible):
    items: list[dict[str, Any]]
    customer_id: str | None = None
    idempotency_key: str | None = None


class OrderUpdate(_Flexible):
    order_id: str
    fields: dict[str, Any]
    idempotency_key: str | None = None


class ListingUpdate(_Flexible):
    product_id: str
    fields: dict[str, Any]
    idempotency_key: str | None = None


class PurchaseOrderCreate(_Flexible):
    supplier_id: str
    lines: list[dict[str, Any]]
    idempotency_key: str | None = None


tool(key="commerce.search_products", name="Search products", description="Search the verified product catalog", provider="commerce", method="search_products", required_permission="commerce:read")
tool(key="commerce.get_product", name="Get product", description="Fetch product details", provider="commerce", method="get_product", required_permission="commerce:read")
tool(key="commerce.price_and_stock", name="Price & stock", description="Current price and stock status", provider="commerce", method="get_price_and_stock", required_permission="commerce:read")
tool(key="commerce.delivery_policy", name="Delivery policy", description="Shipping and returns policy", provider="commerce", method="get_delivery_policy", required_permission="commerce:read")
tool(key="commerce.list_orders", name="List orders", description="List orders", provider="commerce", method="list_orders", required_permission="commerce:read")
tool(key="commerce.get_order", name="Get order", description="Fetch an order", provider="commerce", method="get_order", required_permission="commerce:read")
tool(key="commerce.get_shipment", name="Get shipment", description="Fetch verified shipment/tracking for an order", provider="commerce", method="get_shipment", required_permission="commerce:read")
tool(key="commerce.get_inventory", name="Get inventory", description="Inventory level for a SKU", provider="commerce", method="get_inventory", required_permission="commerce:read")
tool(key="commerce.list_inventory", name="List inventory", description="All inventory records", provider="commerce", method="list_inventory", required_permission="commerce:read")
tool(key="commerce.sales_history", name="Sales history", description="Daily unit sales for a SKU", provider="commerce", method="get_sales_history", required_permission="commerce:read")
tool(key="commerce.supplier_lead_time", name="Supplier lead time", description="Lead time for a SKU", provider="commerce", method="get_supplier_lead_time", required_permission="commerce:read")
tool(key="commerce.brand_guidelines", name="Brand guidelines", description="Brand voice and prohibited claims", provider="commerce", method="get_brand_guidelines", required_permission="commerce:read")
tool(key="commerce.create_cart", name="Prepare cart", description="Create a draft cart (no purchase)", provider="commerce", method="create_cart", side_effect=True, required_permission="commerce:write", risk_level="low", input_model=CartCreate, external_ref_field="id")
tool(key="commerce.update_order", name="Update order", description="Update order fields/notes", provider="commerce", method="update_order", side_effect=True, required_permission="commerce:write", risk_level="medium", input_model=OrderUpdate, external_ref_field="id")
tool(key="commerce.update_listing", name="Publish listing", description="Update a product listing", provider="commerce", method="update_listing", side_effect=True, required_permission="commerce:write", risk_level="medium", input_model=ListingUpdate, external_ref_field="id")
tool(key="commerce.create_purchase_order", name="Create purchase order", description="Issue a replenishment purchase order", provider="commerce", method="create_purchase_order", side_effect=True, idempotent=False, required_permission="procurement:commit", risk_level="critical", input_model=PurchaseOrderCreate, external_ref_field="id")

# ---- Accounting ------------------------------------------------------------
class PayableCreate(_Flexible):
    invoice: dict[str, Any]
    idempotency_key: str | None = None


class ExpenseFlag(_Flexible):
    claim_id: str
    flags: list[dict[str, Any]]
    idempotency_key: str | None = None


class FollowupRecord(_Flexible):
    invoice_id: str
    channel: str
    note: str
    stage: str
    idempotency_key: str | None = None


tool(key="accounting.get_invoice", name="Get invoice", description="Fetch an invoice", provider="accounting", method="get_invoice", required_permission="accounting:read")
tool(key="accounting.list_invoices", name="List invoices", description="List invoices (optionally overdue only)", provider="accounting", method="list_invoices", required_permission="accounting:read")
tool(key="accounting.find_invoices", name="Find invoices", description="Find invoices by vendor/number/amount (duplicate detection)", provider="accounting", method="find_invoices", required_permission="accounting:read")
tool(key="accounting.get_purchase_order", name="Get purchase order", description="Fetch a purchase order", provider="accounting", method="get_purchase_order", required_permission="accounting:read")
tool(key="accounting.list_purchase_orders", name="List purchase orders", description="List purchase orders", provider="accounting", method="list_purchase_orders", required_permission="accounting:read")
tool(key="accounting.list_receipts", name="List goods receipts", description="Goods receipts for a PO", provider="accounting", method="list_receipts", required_permission="accounting:read")
tool(key="accounting.list_expense_claims", name="List expense claims", description="Expense claims", provider="accounting", method="list_expense_claims", required_permission="accounting:read")
tool(key="accounting.get_expense_claim", name="Get expense claim", description="One expense claim", provider="accounting", method="get_expense_claim", required_permission="accounting:read")
tool(key="accounting.expense_policy", name="Expense policy", description="Company expense policy", provider="accounting", method="get_expense_policy", required_permission="accounting:read")
tool(key="accounting.followup_history", name="Follow-up history", description="Payment follow-up history", provider="accounting", method="get_followup_history", required_permission="accounting:read")
tool(key="accounting.cost_ledger", name="Cost ledger", description="Operational cost ledger entries", provider="accounting", method="get_cost_ledger", required_permission="accounting:read")
tool(key="accounting.revenue", name="Revenue", description="Revenue entries", provider="accounting", method="get_revenue", required_permission="accounting:read")
tool(key="accounting.budgets", name="Budgets", description="Budget thresholds by cost centre", provider="accounting", method="get_budgets", required_permission="accounting:read")
tool(key="accounting.create_payable", name="Stage payable for approval", description="Create an AP record pending human approval (never releases payment)", provider="accounting", method="create_payable", side_effect=True, required_permission="accounting:write", risk_level="high", input_model=PayableCreate, external_ref_field="id")
tool(key="accounting.flag_expense", name="Flag expense claim", description="Mark an expense claim for reviewer attention", provider="accounting", method="flag_expense", side_effect=True, required_permission="accounting:write", risk_level="medium", input_model=ExpenseFlag, external_ref_field="id")
tool(key="accounting.record_followup", name="Record follow-up", description="Record a payment follow-up in history", provider="accounting", method="record_followup", side_effect=True, required_permission="accounting:write", risk_level="low", input_model=FollowupRecord, external_ref_field="id")

# ---- WhatsApp --------------------------------------------------------------
class WhatsAppTemplateSend(_Flexible):
    to: str
    template_name: str
    parameters: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None


class WhatsAppTextSend(_Flexible):
    to: str
    text: str
    idempotency_key: str | None = None


tool(key="whatsapp.check_opt_in", name="Check WhatsApp opt-in", description="Consent and 24h window status", provider="whatsapp", method="check_opt_in", required_permission="whatsapp:read")
tool(key="whatsapp.list_templates", name="WhatsApp templates", description="Approved message templates", provider="whatsapp", method="list_templates", required_permission="whatsapp:read")
tool(key="whatsapp.get_conversation", name="WhatsApp conversation", description="Recent conversation with a number", provider="whatsapp", method="get_conversation", required_permission="whatsapp:read")
tool(key="whatsapp.send_template", name="Send WhatsApp template", description="Send an approved template message", provider="whatsapp", method="send_template", side_effect=True, idempotent=False, required_permission="whatsapp:send", risk_level="high", input_model=WhatsAppTemplateSend, external_ref_field="message_id")
tool(key="whatsapp.send_text", name="Send WhatsApp reply", description="Send a free-form reply within the 24h service window", provider="whatsapp", method="send_text", side_effect=True, idempotent=False, required_permission="whatsapp:send", risk_level="medium", input_model=WhatsAppTextSend, external_ref_field="message_id")

# ---- Workspace -------------------------------------------------------------
class CalendarEventCreate(_Flexible):
    title: str
    start: str
    end: str
    attendees: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None


tool(key="workspace.list_employees", name="List employees", description="Authorized employee directory", provider="workspace", method="list_employees", required_permission="workspace:read")
tool(key="workspace.directory_lookup", name="Directory lookup", description="Resolve a person reference via the directory", provider="workspace", method="directory_lookup", required_permission="workspace:read")
tool(key="workspace.get_transcript", name="Get meeting transcript", description="Fetch an authorized meeting transcript", provider="workspace", method="get_transcript", required_permission="workspace:read")
tool(key="workspace.create_calendar_event", name="Create calendar event", description="Create a calendar event", provider="workspace", method="create_calendar_event", side_effect=True, idempotent=False, required_permission="workspace:write", risk_level="low", input_model=CalendarEventCreate, external_ref_field="id")

# ---- Monitoring ------------------------------------------------------------
class AlertCreate(_Flexible):
    title: str
    severity: str
    body: str
    service: str | None = None
    idempotency_key: str | None = None


tool(key="monitoring.get_deployments", name="Deployments", description="Recent deployments", provider="monitoring", method="get_deployments", required_permission="monitoring:read")
tool(key="monitoring.get_metrics", name="Service metrics", description="Error rate / latency telemetry", provider="monitoring", method="get_metrics", required_permission="monitoring:read")
tool(key="monitoring.get_logs", name="Service logs", description="Recent log entries", provider="monitoring", method="get_logs", required_permission="monitoring:read")
tool(key="monitoring.test_environments", name="Test environments", description="Authorized test environments", provider="monitoring", method="get_test_environments", required_permission="monitoring:read")
tool(key="monitoring.create_alert", name="Create incident alert", description="Open an incident alert", provider="monitoring", method="create_alert", side_effect=True, idempotent=False, required_permission="monitoring:write", risk_level="medium", input_model=AlertCreate, external_ref_field="id")

# ---- Procurement -----------------------------------------------------------
class ProcurementPOCreate(_Flexible):
    supplier_id: str
    rfq_id: str
    lines: list[dict[str, Any]]
    total: float
    idempotency_key: str | None = None


tool(key="procurement.get_rfq", name="Get RFQ", description="Fetch a request for quotation", provider="procurement", method="get_rfq", required_permission="procurement:read")
tool(key="procurement.list_quotes", name="List quotes", description="Supplier quotations for an RFQ", provider="procurement", method="list_quotes", required_permission="procurement:read")
tool(key="procurement.get_supplier", name="Get supplier", description="Supplier profile and approval status", provider="procurement", method="get_supplier", required_permission="procurement:read")
tool(key="procurement.list_suppliers", name="List suppliers", description="All suppliers", provider="procurement", method="list_suppliers", required_permission="procurement:read")
tool(key="procurement.get_policy", name="Procurement policy", description="Procurement policy", provider="procurement", method="get_policy", required_permission="procurement:read")
tool(key="procurement.create_purchase_order", name="Issue purchase order", description="Commit to a supplier purchase order", provider="procurement", method="create_purchase_order", side_effect=True, idempotent=False, required_permission="procurement:commit", risk_level="critical", input_model=ProcurementPOCreate, external_ref_field="id")

# ---- Feedback / metrics ----------------------------------------------------
tool(key="feedback.list", name="List feedback", description="Customer feedback, reviews, tickets, feature requests", provider="feedback", method="list_feedback", required_permission="feedback:read")
tool(key="metrics.list", name="List metrics", description="Available business metrics", provider="metrics", method="list_metrics", required_permission="metrics:read")
tool(key="metrics.query", name="Query metric", description="Time series for a metric", provider="metrics", method="query_metric", required_permission="metrics:read")
tool(key="metrics.list_sops", name="List SOPs", description="Approved standard operating procedures", provider="metrics", method="list_sops", required_permission="metrics:read")
tool(key="metrics.operational_records", name="Operational records", description="Records of executed process steps", provider="metrics", method="list_operational_records", required_permission="metrics:read")

# ---- Platform-internal tools (no external provider) ------------------------
class PlatformTaskCreate(_Flexible):
    title: str
    description: str = ""
    priority: str = "medium"
    owner_user_id: str | None = None
    owner_name: str | None = None
    due_at: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None


class PlatformTaskEscalate(_Flexible):
    task_id: str
    level: int = 1
    note: str = ""
    idempotency_key: str | None = None


class KnowledgeSearch(_Flexible):
    query: str
    collection: str | None = None
    limit: int = 5


tool(key="platform.create_task", name="Create task", description="Create a task in OpsPilot's task board", provider="platform", method="create_task", side_effect=True, required_permission="tasks:write", risk_level="low", input_model=PlatformTaskCreate, external_ref_field="id")
tool(key="platform.escalate_task", name="Escalate task", description="Raise the escalation level of a task and notify its owner", provider="platform", method="escalate_task", side_effect=True, required_permission="tasks:write", risk_level="medium", input_model=PlatformTaskEscalate, external_ref_field="id")
tool(key="platform.list_tasks", name="List tasks", description="List OpsPilot tasks", provider="platform", method="list_tasks", required_permission="tasks:read")
tool(key="platform.workflow_usage", name="Workflow usage", description="Workflow run counts, AI cost and estimated time saved by workflow", provider="platform", method="workflow_usage", required_permission="tasks:read")
tool(key="platform.search_knowledge", name="Search knowledge base", description="Retrieve passages from authorized tenant documents", provider="platform", method="search_knowledge", required_permission="documents:read", input_model=KnowledgeSearch)
tool(key="platform.list_documents", name="List documents", description="List authorized documents in a collection", provider="platform", method="list_documents", required_permission="documents:read")
class InboundMessageRecord(_Flexible):
    phone: str
    text: str
    message_id: str | None = None
    idempotency_key: str | None = None


tool(key="platform.record_inbound_message", name="Record inbound message", description="Persist an inbound channel message (opens the WhatsApp 24h service window)", provider="platform", method="record_inbound_message", side_effect=True, required_permission="whatsapp:read", risk_level="low", input_model=InboundMessageRecord, external_ref_field="id")
tool(key="platform.open_incident", name="Open incident", description="Record a platform incident for operators", provider="platform", method="open_incident", side_effect=True, required_permission="incidents:write", risk_level="low", external_ref_field="id")
tool(key="platform.start_workflow", name="Start workflow", description="Delegate to another workflow (bounded depth)", provider="platform", method="start_workflow", side_effect=True, required_permission="workflows:write", risk_level="medium", external_ref_field="id")
