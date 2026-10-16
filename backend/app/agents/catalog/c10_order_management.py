"""Agent 10 - Order Management.

Detects delayed, cancelled, failed and exceptional orders from authoritative
order and shipment data, drafts customer updates containing only verified
facts, opens internal tickets and routes unresolved cases. It never invents
tracking data and never marks an order fulfilled without carrier evidence.
"""

from __future__ import annotations

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
from app.core.errors import NotFound

TERMINAL_OK = {"delivered", "fulfilled", "completed"}


class OrdersIn(AgentInput):
    order_ids: list[str] | None = None
    scan_all: bool | None = True
    unfulfilled_after_days: int = Field(default=3, ge=1, le=60)
    notify_customers: bool = True


class OrderException(BaseModel):
    order_id: str
    customer_id: str | None
    exception_type: str
    severity: str
    detail: str
    tracking_verified: bool
    carrier: str | None = None
    tracking_number: str | None = None
    expected_delivery: str | None = None
    recommended_action: str
    customer_update_draft: str | None = None


class OrdersOut(BaseModel):
    scanned: int
    exceptions: list[OrderException]
    counts: dict[str, int]
    affected_customer_ids: list[str]
    fulfilment_corrections: list[dict[str, Any]] = Field(default_factory=list)


@register
class OrderManagementAgent(BaseAgent):
    spec = AgentSpec(
        key="order_management",
        name="Order Management Agent",
        department="ecommerce",
        version="1.1.0",
        description="Monitors orders and shipments to catch delays, cancellations and failures, drafts verified customer updates and routes unresolved cases.",
        use_cases=["Delay detection", "Failed payment follow-up", "Proactive customer updates"],
        input_model=OrdersIn,
        output_model=OrdersOut,
        allowed_tools=["commerce.list_orders", "commerce.get_order", "commerce.get_shipment", "crm.get_customer", "email.send", "helpdesk.create_ticket", "commerce.update_order"],
        permission_scopes=["commerce:read", "commerce:write", "crm:read", "email:send", "helpdesk:write"],
        policies=["verified_tracking_only", "no_unverified_fulfilment", "customer_updates_require_approval"],
        approval_rules=[ApprovalRule(action_type="email.send", condition="customer-facing order updates", required_permission="email:send"), ApprovalRule(action_type="commerce.update_order", condition="order status changes")],
        timeout_seconds=120,
        token_budget=6000,
        risk_level="medium",
        baseline_minutes_saved=20,
    )

    def run(self, ctx: AgentContext, payload: OrdersIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        orders: list[dict[str, Any]] = []
        if payload.order_ids:
            for oid in payload.order_ids:
                try:
                    orders.append(services.tools.call("commerce.get_order", order_id=oid))
                except NotFound:
                    result.warnings.append(f"Order {oid} not found")
        else:
            orders = services.tools.call("commerce.list_orders", limit=500).get("items", [])

        exceptions: list[OrderException] = []
        corrections: list[dict[str, Any]] = []
        for o in orders:
            oid = str(o["id"])
            status = str(o.get("status") or "").lower()
            ship = services.tools.call("commerce.get_shipment", order_id=oid)
            found = bool(ship.get("found"))
            created = parse_dt(o.get("created_at"))
            expected = parse_dt(ship.get("expected_delivery")) if found else None
            carrier_status = str(ship.get("status") or "").lower() if found else ""
            exc: tuple[str, str, str, str] | None = None  # type, severity, detail, recommended
            if status in {"cancelled", "canceled"}:
                exc = ("cancelled", "medium", f"Order cancelled ({o.get('cancel_reason') or 'reason not recorded'})", "Confirm refund status with finance and inform the customer")
            elif status in {"payment_failed", "failed"}:
                exc = ("payment_failed", "high", "Payment failed; order is on hold", "Ask the customer to update payment details")
            elif found and carrier_status in {"exception", "lost", "returned_to_sender"}:
                exc = ("carrier_exception", "high", f"Carrier reports '{carrier_status}'", "Open a carrier claim and offer the customer options per policy")
            elif found and expected and expected < ctx.now and carrier_status != "delivered" and status not in TERMINAL_OK:
                days = (ctx.now - expected).days
                exc = ("delayed", "high" if days >= 3 else "medium", f"Expected {expected.date()} — {days} day(s) late; carrier status '{carrier_status or 'unknown'}'", "Contact the carrier and update the customer")
            elif not found and status not in TERMINAL_OK and created and (ctx.now - created).days >= payload.unfulfilled_after_days:
                exc = ("unfulfilled", "medium", f"No shipment {(ctx.now - created).days} days after order", "Check warehouse fulfilment queue")
            if found and carrier_status == "delivered" and status not in TERMINAL_OK and ship.get("delivered_at"):
                corrections.append({"order_id": oid, "evidence": f"carrier delivered_at {ship.get('delivered_at')}", "proposed_status": "fulfilled"})
                result.add_evidence(f"commerce:shipment:{oid}", excerpt=f"delivered {ship.get('delivered_at')}", source_type="commerce")
                result.proposed_actions.append(ProposedAction(action_type="commerce.update_order", tool_key="commerce.update_order", payload={"order_id": oid, "fields": {"status": "fulfilled", "fulfilment_evidence": f"carrier:{ship.get('carrier')}:{ship.get('tracking_number')}:delivered_at={ship.get('delivered_at')}"}}, reason="Carrier confirms delivery; order still open", risk_level="medium", requires_approval=True, evidence_refs=[f"commerce:shipment:{oid}"]))
            if not exc:
                continue
            result.add_evidence(f"commerce:order:{oid}", excerpt=f"status={status}", source_type="commerce")
            if found:
                result.add_evidence(f"commerce:shipment:{oid}", excerpt=f"{ship.get('carrier')} {ship.get('tracking_number')} {carrier_status}", source_type="commerce")
            draft = None
            if payload.notify_customers and exc[0] in {"delayed", "carrier_exception", "payment_failed", "cancelled"}:
                lines = [f"Hi,\n\nWe wanted to give you an update on order {oid}."]
                if exc[0] == "delayed":
                    lines.append(f"Your parcel with {ship.get('carrier')} (tracking {ship.get('tracking_number')}) is running behind the expected date of {expected.date() if expected else 'n/a'}. We're following up with the carrier.")
                elif exc[0] == "carrier_exception":
                    lines.append(f"The carrier ({ship.get('carrier')}) has reported a delivery problem. Our team is investigating and will contact you with options.")
                elif exc[0] == "payment_failed":
                    lines.append("We weren't able to process the payment. Please update your payment details in your account so we can ship your order.")
                else:
                    lines.append("Your order has been cancelled. If you didn't request this, please reply and we'll help.")
                lines.append("\nThank you for your patience,\nCustomer Care")
                draft = "\n".join(lines)
            exceptions.append(OrderException(order_id=oid, customer_id=o.get("customer_id"), exception_type=exc[0], severity=exc[1], detail=exc[2], tracking_verified=found, carrier=ship.get("carrier") if found else None, tracking_number=ship.get("tracking_number") if found else None, expected_delivery=ship.get("expected_delivery") if found else None, recommended_action=exc[3], customer_update_draft=draft))

        for e in exceptions:
            result.proposed_actions.append(ProposedAction(action_type="helpdesk.create_ticket", tool_key="helpdesk.create_ticket", payload={"subject": f"Order {e.order_id}: {e.exception_type.replace('_', ' ')}", "description": f"{e.detail}\nRecommended: {e.recommended_action}", "customer_id": e.customer_id, "category": "order_exception", "priority": e.severity, "sla_hours": 8 if e.severity == "high" else 24}, reason="Track unresolved order exception", risk_level="low", evidence_refs=[f"commerce:order:{e.order_id}"], estimated_minutes_saved=4))
            if e.customer_update_draft and e.customer_id:
                try:
                    cust = services.tools.call("crm.get_customer", customer_id=e.customer_id)
                except NotFound:
                    cust = {}
                if cust.get("email"):
                    result.proposed_actions.append(ProposedAction(action_type="email.send", tool_key="email.send", payload={"to": cust["email"], "subject": f"Update on your order {e.order_id}", "body": e.customer_update_draft}, reason=f"Proactive {e.exception_type} update with verified facts only", risk_level="high", evidence_refs=[f"commerce:order:{e.order_id}"], estimated_minutes_saved=4))
                else:
                    result.missing_information.append(f"No verified email for customer of order {e.order_id}")
        counts: dict[str, int] = {}
        for e in exceptions:
            counts[e.exception_type] = counts.get(e.exception_type, 0) + 1
        affected = sorted({e.customer_id for e in exceptions if e.customer_id})
        result.data = OrdersOut(scanned=len(orders), exceptions=exceptions, counts=counts, affected_customer_ids=affected, fulfilment_corrections=corrections).model_dump()
        result.summary = f"Scanned {len(orders)} order(s): {len(exceptions)} exception(s) " + (f"({', '.join(f'{v} {k}' for k, v in counts.items())})" if counts else "")
        result.confidence = 0.9
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved if exceptions else 5
        return result
