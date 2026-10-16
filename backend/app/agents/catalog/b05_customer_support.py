"""Agent 5 - Customer Support.

Answers questions only from the authorised knowledge base and verified account
/ order data, citing every source. Unsupported, sensitive or complex requests
are escalated instead of guessed.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentResult, AgentSpec, BaseAgent, ProposedAction
from app.agents.common import contains_any, guard_untrusted, sentences, tokenize
from app.agents.registry import register
from app.agents.services import AgentServices
from app.core.errors import NotFound

SENSITIVE = ["lawyer", "lawsuit", "legal action", "sue", "fraud", "chargeback", "data breach", "hacked", "stolen", "injury", "injured", "unsafe", "harassment", "discrimination", "gdpr", "delete my data", "privacy"]
COMPLAINT = ["complaint", "unacceptable", "terrible", "worst", "angry", "furious", "disappointed", "refund", "broken", "damaged", "never arrived", "still waiting", "ridiculous", "scam"]
HUMAN = ["speak to a human", "talk to a person", "real person", "human agent", "manager", "supervisor"]
ORDER_ID = re.compile(r"\b(ORD-\d{3,8}|#\d{4,8})\b", re.I)


class SupportIn(AgentInput):
    message: str = Field(min_length=1, max_length=8000)
    customer_id: str | None = None
    channel: str | None = "email"
    order_id: str | None = None


class Citation(BaseModel):
    ref: str
    title: str | None = None
    excerpt: str | None = None


class DraftAnswer(BaseModel):
    answer: str = Field(max_length=3000)
    citations: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    unanswerable: bool = False


class SupportOut(BaseModel):
    answer: str
    citations: list[Citation]
    confidence: float
    escalate: bool
    is_complaint: bool
    escalation_reason: str | None = None
    category: str
    order_status: dict[str, Any] | None = None
    customer_verified: bool


@register
class CustomerSupportAgent(BaseAgent):
    spec = AgentSpec(
        key="customer_support",
        name="Customer Support Agent",
        department="customer_support",
        version="1.3.0",
        description="Answers customer questions from the authorised knowledge base and verified account/order data with citations, escalating anything unsupported or sensitive.",
        use_cases=["FAQ deflection", "Order status", "Policy questions", "Smart escalation"],
        input_model=SupportIn,
        output_model=SupportOut,
        allowed_tools=["platform.search_knowledge", "crm.get_customer", "commerce.get_order", "commerce.get_shipment", "commerce.delivery_policy", "helpdesk.create_ticket"],
        permission_scopes=["documents:read", "crm:read", "commerce:read", "helpdesk:write"],
        policies=["cite_sources", "no_unsupported_answers", "escalate_sensitive"],
        timeout_seconds=60,
        token_budget=8000,
        risk_level="medium",
        baseline_minutes_saved=7,
    )

    def run(self, ctx: AgentContext, payload: SupportIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        msg = payload.message
        wrapped = guard_untrusted(result, msg, "customer_message", 8000)
        injected = bool(result.data.get("_security", {}).get("prompt_injection_detected"))

        customer: dict[str, Any] | None = None
        if payload.customer_id:
            try:
                customer = services.tools.call("crm.get_customer", customer_id=payload.customer_id)
                result.add_evidence(f"crm:customer:{payload.customer_id}", excerpt=f"{customer.get('name')} ({customer.get('tier', 'standard')})", source_type="crm")
            except NotFound:
                result.warnings.append("Customer id not found; account-specific details withheld")

        order_id = payload.order_id or (ORDER_ID.search(msg).group(1).upper().replace("#", "ORD-") if ORDER_ID.search(msg) else None)
        order_status: dict[str, Any] | None = None
        citations: list[Citation] = []
        if order_id:
            try:
                order = services.tools.call("commerce.get_order", order_id=order_id)
                if customer and order.get("customer_id") and order["customer_id"] != payload.customer_id:
                    result.warnings.append("Order does not belong to this customer; details withheld")
                    order = None  # type: ignore[assignment]
                if order:
                    ship = services.tools.call("commerce.get_shipment", order_id=order_id)
                    order_status = {"order_id": order_id, "status": order.get("status"), "carrier": ship.get("carrier") if ship.get("found") else None, "tracking_number": ship.get("tracking_number") if ship.get("found") else None, "expected_delivery": ship.get("expected_delivery") if ship.get("found") else None, "tracking_available": bool(ship.get("found"))}
                    result.add_evidence(f"commerce:order:{order_id}", excerpt=f"status={order.get('status')}", source_type="commerce")
                    citations.append(Citation(ref=f"commerce:order:{order_id}", title=f"Order {order_id}", excerpt=f"Status: {order.get('status')}"))
                    if ship.get("found"):
                        result.add_evidence(f"commerce:shipment:{order_id}", excerpt=f"{ship.get('carrier')} {ship.get('tracking_number')}", source_type="commerce")
                        citations.append(Citation(ref=f"commerce:shipment:{order_id}", title="Shipment", excerpt=f"{ship.get('carrier')} · expected {ship.get('expected_delivery')}"))
            except NotFound:
                result.warnings.append(f"Order {order_id} not found")

        hits = services.tools.call("platform.search_knowledge", query=msg[:500], collection="kb", limit=4).get("items", [])
        for h in hits:
            result.add_evidence(h["ref"], excerpt=h["text"][:200], source_type="knowledge_base")
        allowed_refs = {h["ref"] for h in hits} | {c.ref for c in citations}

        sensitive = contains_any(msg, SENSITIVE)
        complaint = contains_any(msg, COMPLAINT)
        human = contains_any(msg, HUMAN)
        category = "order_status" if order_status else "complaint" if complaint else "sensitive" if sensitive else "general"

        def heuristic() -> DraftAnswer:
            if order_status:
                if order_status["tracking_available"]:
                    text = f"Your order {order_id} is currently '{order_status['status']}'. It is with {order_status['carrier']} (tracking {order_status['tracking_number']}), expected delivery {order_status['expected_delivery']}."
                else:
                    text = f"Your order {order_id} is currently '{order_status['status']}'. Tracking information is not available yet."
                return DraftAnswer(answer=text, citations=[c.ref for c in citations], confidence=0.9)
            if not hits or hits[0]["score"] < 1.0:
                return DraftAnswer(answer="", citations=[], confidence=0.0, unanswerable=True)
            q = set(tokenize(msg))
            best = sorted(((len(q & set(tokenize(s))), s) for h in hits[:2] for s in sentences(h["text"])), key=lambda x: -x[0])
            chosen = [s for score, s in best[:3] if score > 0]
            if not chosen:
                return DraftAnswer(answer="", citations=[], confidence=0.0, unanswerable=True)
            conf = min(0.9, 0.4 + hits[0]["score"] / 10)
            return DraftAnswer(answer=" ".join(chosen), citations=[hits[0]["ref"]] + ([hits[1]["ref"]] if len(hits) > 1 and len(chosen) > 1 else []), confidence=round(conf, 2))

        context_block = "\n\n".join(f"[{h['ref']}] ({h['document_name']}{' / ' + h['section'] if h.get('section') else ''})\n{h['text']}" for h in hits)
        if order_status:
            context_block += f"\n\n[commerce:order:{order_id}] Verified order data: {order_status}"
        draft = services.structured(
            task="support_answer",
            schema=DraftAnswer,
            system=(
                "You are a customer support agent. Answer ONLY using the sources provided. Cite source refs exactly as given in brackets. "
                "If the sources do not contain the answer, set unanswerable=true and leave the answer empty. Never promise refunds, credits or timelines not stated in the sources."
            ),
            user=f"Sources:\n{context_block or '(none)'}\n\nCustomer message:\n{wrapped}",
            heuristic=heuristic,
        )
        valid_citations = [c for c in draft.citations if c in allowed_refs]
        if len(valid_citations) < len(draft.citations):
            result.warnings.append("Removed citations that did not match retrieved sources")
        unsupported = (not draft.answer.strip()) or draft.unanswerable or not valid_citations

        escalate, reason = False, None
        if sensitive:
            escalate, reason = True, f"Sensitive topic detected ({', '.join(sensitive)})"
        elif complaint:
            escalate, reason = True, "Customer complaint - routed to complaint resolution"
        elif human:
            escalate, reason = True, "Customer requested a human agent"
        elif injected:
            escalate, reason = True, "Message contains instructions aimed at the assistant; routed to a human"
        elif unsupported:
            escalate, reason = True, "No authorised source supports an answer"
        elif draft.confidence < float(ctx.agent_config.get("min_confidence", 0.5)):
            escalate, reason = True, f"Low confidence ({draft.confidence:.2f})"

        is_complaint = bool(complaint) and not sensitive
        if escalate and not unsupported and draft.answer:
            answer = draft.answer + "\n\nI've also passed your message to a specialist who will follow up."
        elif escalate:
            answer = "Thanks for reaching out. I've passed your request to a specialist who will get back to you shortly."
        else:
            answer = draft.answer

        doc_titles = {h["ref"]: h["document_name"] for h in hits}
        texts = {h["ref"]: h["text"][:200] for h in hits}
        all_citations = citations + [Citation(ref=r, title=doc_titles.get(r), excerpt=texts.get(r)) for r in valid_citations if r not in {c.ref for c in citations}]

        if escalate and not is_complaint:
            result.proposed_actions.append(ProposedAction(
                action_type="helpdesk.create_ticket", tool_key="helpdesk.create_ticket",
                payload={"subject": f"Escalation: {msg[:80]}", "description": f"Reason: {reason}\nChannel: {payload.channel}\n\nCustomer message:\n{msg[:2000]}", "customer_id": payload.customer_id, "category": "sensitive" if sensitive else "specialist", "priority": "high" if sensitive else "medium", "sla_hours": 8 if sensitive else 24},
                reason=reason or "escalation", risk_level="low", estimated_minutes_saved=3,
            ))
        result.data = SupportOut(answer=answer, citations=all_citations, confidence=draft.confidence if not escalate else min(draft.confidence, 0.5), escalate=escalate, is_complaint=is_complaint, escalation_reason=reason, category=category, order_status=order_status, customer_verified=customer is not None).model_dump()
        result.status = "escalated" if escalate else "completed"
        result.summary = f"{'Escalated' if escalate else 'Answered'} ({category})" + (f": {reason}" if reason else f" with {len(all_citations)} citation(s)")
        result.confidence = draft.confidence
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved if not escalate else 2
        return result
