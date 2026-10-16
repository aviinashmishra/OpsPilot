"""Agent 19 - Payment Follow-up.

Reads invoice status and due dates from the authoritative accounting system,
drafts reminders from approved templates by dunning stage, respects dispute
status, communication limits and contact preferences, and records follow-up
history. It never initiates transfers and never claims payment was received.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import (
    AgentContext,
    AgentInput,
    AgentResult,
    AgentSpec,
    ApprovalRule,
    BaseAgent,
    ProposedAction,
)
from app.agents.common import parse_dt
from app.agents.registry import register
from app.agents.services import AgentServices

STAGES = [(0, "friendly"), (7, "firm"), (21, "final")]


class FollowupIn(AgentInput):
    invoice_ids: list[str] | None = None
    min_days_between_contacts: int = Field(default=5, ge=1, le=60)
    max_invoices: int = Field(default=200, ge=1, le=2000)


class Reminder(BaseModel):
    invoice_id: str
    customer: str | None
    contact_email: str | None
    amount_due: float
    currency: str
    due_date: str | None
    days_overdue: int
    stage: str
    template_id: str | None
    skipped_reason: str | None = None
    previous_followups: int
    subject: str | None = None
    body: str | None = None


class FollowupOut(BaseModel):
    reviewed: int
    reminders_drafted: int
    skipped: int
    reminders: list[Reminder]
    total_outstanding: float


@register
class PaymentFollowupAgent(BaseAgent):
    spec = AgentSpec(
        key="payment_followup",
        name="Payment Follow-up Agent",
        department="finance_admin",
        version="1.0.3",
        description="Drafts policy-compliant payment reminders from approved templates based on authoritative invoice status, respecting disputes and contact limits.",
        use_cases=["Dunning cadences", "AR aging follow-up", "Escalation to collections review"],
        input_model=FollowupIn,
        output_model=FollowupOut,
        allowed_tools=["accounting.list_invoices", "accounting.get_invoice", "accounting.followup_history", "email.list_templates", "crm.check_consent", "email.send", "accounting.record_followup", "platform.create_task"],
        permission_scopes=["accounting:read", "accounting:write", "email:read", "email:send", "crm:read", "tasks:write"],
        policies=["authoritative_status_only", "approved_templates", "dispute_hold", "contact_limits", "no_payment_claims", "no_transfers"],
        approval_rules=[ApprovalRule(action_type="email.send", condition="all customer reminders", required_permission="email:send")],
        timeout_seconds=90,
        token_budget=2000,
        risk_level="high",
        baseline_minutes_saved=12,
    )

    def run(self, ctx: AgentContext, payload: FollowupIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        if payload.invoice_ids:
            invoices = []
            for i in payload.invoice_ids[: payload.max_invoices]:
                try:
                    invoices.append(services.tools.call("accounting.get_invoice", invoice_id=i))
                except Exception:  # noqa: BLE001
                    result.warnings.append(f"Invoice {i} not found")
        else:
            invoices = services.tools.call("accounting.list_invoices", overdue_only=True, limit=payload.max_invoices).get("items", [])
        templates = {t.get("stage") or t.get("id"): t for t in services.tools.call("email.list_templates", category="dunning").get("items", [])}
        reminders: list[Reminder] = []
        outstanding = 0.0
        for inv in invoices:
            iid = str(inv["id"])
            ref = f"accounting:invoice:{iid}"
            due = parse_dt(inv.get("due_date"))
            amt = float(inv.get("balance_due", inv.get("total", 0)) or 0)
            status = str(inv.get("status") or "").lower()
            days = (ctx.now - due).days if due else 0
            result.add_evidence(ref, excerpt=f"status={status} due={inv.get('due_date')} balance={amt}", source_type="accounting")
            hist = services.tools.call("accounting.followup_history", invoice_id=iid).get("items", [])
            last = max((parse_dt(h.get("at")) for h in hist if parse_dt(h.get("at"))), default=None)
            stage = next((name for d, name in reversed(STAGES) if days >= d), "friendly")
            base = dict(invoice_id=iid, customer=inv.get("customer_name"), contact_email=inv.get("contact_email"), amount_due=amt, currency=inv.get("currency", "USD"), due_date=inv.get("due_date"), days_overdue=max(days, 0), stage=stage, template_id=None, previous_followups=len(hist))
            skip = None
            if status in {"paid", "void", "written_off"}:
                skip = f"Invoice is {status}"
            elif status == "disputed" or inv.get("dispute_open"):
                skip = "Dispute open — reminders on hold per policy"
            elif not due or days <= 0:
                skip = "Not yet due"
            elif inv.get("payment_plan"):
                skip = "Payment plan in place"
            elif last and (ctx.now - last) < timedelta(days=payload.min_days_between_contacts):
                skip = f"Contacted {(ctx.now - last).days} day(s) ago (min interval {payload.min_days_between_contacts})"
            elif not inv.get("contact_email"):
                skip = "No contact email on the invoice"
                result.missing_information.append(f"Contact email for invoice {iid}")
            else:
                consent = services.tools.call("crm.check_consent", email=inv["contact_email"])
                if consent.get("do_not_contact"):
                    skip = "Contact marked do-not-contact"
            if skip:
                reminders.append(Reminder(**base, skipped_reason=skip))
                continue
            outstanding += amt
            tpl = templates.get(stage)
            if not tpl:
                reminders.append(Reminder(**base, skipped_reason=f"No approved template for stage '{stage}'"))
                result.missing_information.append(f"Approved dunning template for stage '{stage}'")
                continue
            fill = {"customer": inv.get("customer_name") or "Customer", "invoice_number": inv.get("invoice_number") or iid, "amount": f"{inv.get('currency', 'USD')} {amt:,.2f}", "due_date": str(inv.get("due_date")), "days_overdue": str(max(days, 0))}
            subject = _fill(tpl.get("subject", "Reminder: invoice {invoice_number}"), fill)
            body = _fill(tpl.get("body", ""), fill) + "\n\nIf you have already sent payment, please disregard this notice; we will confirm once it is received."
            reminders.append(Reminder(**{**base, "template_id": tpl.get("id")}, subject=subject, body=body))
            result.proposed_actions.append(ProposedAction(action_type="email.send", tool_key="email.send", payload={"to": inv["contact_email"], "subject": subject, "body": body, "template_id": tpl.get("id"), "amount": amt}, reason=f"{stage.title()} reminder, {days} day(s) overdue", risk_level="high", evidence_refs=[ref], estimated_minutes_saved=6))
            result.proposed_actions.append(ProposedAction(action_type="accounting.record_followup", tool_key="accounting.record_followup", payload={"invoice_id": iid, "channel": "email", "note": f"{stage} reminder drafted (template {tpl.get('id')})", "stage": stage}, reason="Maintain follow-up history", risk_level="low", evidence_refs=[ref]))
            if stage == "final":
                result.proposed_actions.append(ProposedAction(action_type="platform.create_task", tool_key="platform.create_task", payload={"title": f"Collections review: invoice {inv.get('invoice_number') or iid} ({days}d overdue)", "description": f"Final reminder stage reached. Balance {amt:,.2f}. Decide on collections escalation.", "priority": "high", "labels": ["ar", "collections"], "evidence_refs": [ref]}, reason="Escalation record", risk_level="low"))
        drafted = [r for r in reminders if r.body]
        result.data = FollowupOut(reviewed=len(invoices), reminders_drafted=len(drafted), skipped=len(reminders) - len(drafted), reminders=reminders, total_outstanding=round(outstanding, 2)).model_dump()
        result.summary = f"{len(invoices)} overdue invoice(s): {len(drafted)} reminder(s) drafted, {len(reminders) - len(drafted)} skipped by policy"
        result.confidence = 0.95
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved if drafted else 0
        return result


def _fill(template: str, values: dict[str, Any]) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return out
