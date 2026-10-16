"""Agent 7 - WhatsApp Business.

Handles inbound WhatsApp messages via the official Business Platform (or the
sandbox adapter): FAQs, product inquiries, order status, lead capture,
opt-outs and escalation. Enforces opt-in, the 24-hour customer-service window
(outside it only approved templates may be sent) and per-number rate limits.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentResult, AgentSpec, BaseAgent, ProposedAction
from app.agents.common import contains_any, guard_untrusted, parse_dt, sentences, tokenize
from app.agents.registry import register
from app.agents.services import AgentServices
from app.core.errors import NotFound

Intent = Literal["opt_out", "human", "order_status", "lead", "product_inquiry", "faq", "greeting", "unknown"]
OPT_OUT = ["stop", "unsubscribe", "opt out", "opt-out", "cancel messages", "don't message", "do not message"]
HUMAN = ["agent", "human", "person", "representative", "call me", "complaint", "manager"]
LEAD = ["quote", "pricing for", "bulk", "wholesale", "for my business", "for our company", "demo", "partnership", "distributor"]
PRODUCT = ["do you have", "looking for", "recommend", "in stock", "price of", "how much is", "available", "buy"]
ORDER = re.compile(r"\b(ORD-\d{3,8})\b", re.I)


class WhatsAppIn(AgentInput):
    phone: str = Field(min_length=6, max_length=20)
    message: str = Field(min_length=1, max_length=4096)
    customer_id: str | None = None
    message_id: str | None = None
    profile_name: str | None = None


class IntentOut(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0, le=1)


class WhatsAppOut(BaseModel):
    intent: str
    reply_text: str | None
    reply_mode: Literal["session_text", "template", "none"]
    template_name: str | None = None
    within_24h_window: bool
    opted_in: bool
    lead_captured: bool
    escalated: bool
    citations: list[str]
    rate_limited: bool = False


def classify(msg: str) -> IntentOut:
    m = msg.lower().strip()
    if m in {"stop", "unsubscribe"} or contains_any(m, OPT_OUT):
        return IntentOut(intent="opt_out", confidence=0.95)
    if ORDER.search(msg) or "my order" in m or "where is my" in m:
        return IntentOut(intent="order_status", confidence=0.9)
    if contains_any(m, HUMAN):
        return IntentOut(intent="human", confidence=0.85)
    if contains_any(m, LEAD):
        return IntentOut(intent="lead", confidence=0.8)
    if contains_any(m, PRODUCT):
        return IntentOut(intent="product_inquiry", confidence=0.75)
    if m in {"hi", "hello", "hey", "hola", "good morning"}:
        return IntentOut(intent="greeting", confidence=0.9)
    if "?" in m or len(tokenize(m)) >= 2:
        return IntentOut(intent="faq", confidence=0.6)
    return IntentOut(intent="unknown", confidence=0.3)


@register
class WhatsAppBusinessAgent(BaseAgent):
    spec = AgentSpec(
        key="whatsapp_business",
        name="WhatsApp Business Agent",
        department="customer_support",
        version="1.0.2",
        description="Answers WhatsApp customers (FAQs, products, orders), captures leads and opt-outs and escalates, respecting consent, the 24-hour window and approved templates.",
        use_cases=["WhatsApp FAQ", "Order status via chat", "Lead capture", "Opt-out handling"],
        input_model=WhatsAppIn,
        output_model=WhatsAppOut,
        allowed_tools=["platform.record_inbound_message", "whatsapp.check_opt_in", "whatsapp.list_templates", "whatsapp.get_conversation", "platform.search_knowledge", "commerce.search_products", "commerce.get_order", "commerce.get_shipment", "whatsapp.send_text", "whatsapp.send_template", "crm.upsert_lead", "crm.update_consent", "helpdesk.create_ticket"],
        permission_scopes=["whatsapp:read", "whatsapp:send", "crm:write", "helpdesk:write", "commerce:read", "documents:read"],
        policies=["whatsapp_opt_in", "24h_service_window", "approved_templates_only", "rate_limits"],
        timeout_seconds=45,
        token_budget=5000,
        risk_level="medium",
        model_tier="fast",
        baseline_minutes_saved=4,
    )

    def run(self, ctx: AgentContext, payload: WhatsAppIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        wrapped = guard_untrusted(result, payload.message, "whatsapp_message", 4096)
        intent = services.structured(task="whatsapp_intent", schema=IntentOut, system="Classify the WhatsApp message intent: opt_out, human, order_status, lead, product_inquiry, faq, greeting, unknown.", user=wrapped, heuristic=lambda: classify(payload.message), tier="fast")
        if result.data.get("_security", {}).get("prompt_injection_detected"):
            intent = IntentOut(intent="human", confidence=0.9)

        opt = services.tools.call("whatsapp.check_opt_in", phone=payload.phone)
        # The inbound message being handled opens/renews the 24h customer-service window.
        # Record it first so the window is verifiable by the channel adapter at send time.
        result.proposed_actions.append(ProposedAction(action_type="whatsapp.record_inbound", tool_key="platform.record_inbound_message", payload={"phone": payload.phone, "text": payload.message[:4096], "message_id": payload.message_id}, reason="Persist inbound message (opens 24h service window)", risk_level="low"))
        within_window = True
        opted_in = bool(opt.get("opted_in"))
        convo = services.tools.call("whatsapp.get_conversation", phone=payload.phone, limit=50).get("items", [])
        recent_out = [m for m in convo if m.get("direction") == "outbound" and (parse_dt(m.get("at")) or ctx.now) >= ctx.now - timedelta(hours=1)]
        rate_limited = len(recent_out) >= int(ctx.agent_config.get("max_messages_per_hour", 5))
        result.add_evidence(f"whatsapp:consent:{payload.phone[-4:]}", excerpt=f"opted_in={opted_in}", source_type="whatsapp")

        reply: str | None = None
        citations: list[str] = []
        lead_captured = escalated = False
        it = intent.intent

        if it == "opt_out":
            result.proposed_actions.append(ProposedAction(action_type="crm.update_consent", tool_key="crm.update_consent", payload={"phone": payload.phone, "unsubscribed": True, "channel": "whatsapp"}, reason="Customer opted out on WhatsApp", risk_level="low"))
            reply = "You've been unsubscribed and won't receive further messages from us. Reply START anytime to opt back in."
        elif it == "order_status":
            m = ORDER.search(payload.message)
            if not m:
                reply = "I can check that for you — could you share your order number (it looks like ORD-12345)?"
                result.missing_information.append("order number")
            else:
                oid = m.group(1).upper()
                try:
                    order = services.tools.call("commerce.get_order", order_id=oid)
                    ship = services.tools.call("commerce.get_shipment", order_id=oid)
                    result.add_evidence(f"commerce:order:{oid}", excerpt=f"status={order.get('status')}", source_type="commerce")
                    citations.append(f"commerce:order:{oid}")
                    if ship.get("found"):
                        reply = f"Order {oid} is '{order.get('status')}' with {ship.get('carrier')} (tracking {ship.get('tracking_number')}), expected {ship.get('expected_delivery')}."
                        citations.append(f"commerce:shipment:{oid}")
                        result.add_evidence(f"commerce:shipment:{oid}", excerpt=str(ship.get("tracking_number")), source_type="commerce")
                    else:
                        reply = f"Order {oid} is '{order.get('status')}'. Tracking isn't available yet — we'll share it as soon as it ships."
                except NotFound:
                    reply = f"I couldn't find order {oid}. Could you double-check the number?"
        elif it == "product_inquiry":
            items = services.tools.call("commerce.search_products", query=payload.message[:200], limit=3).get("items", [])
            if items:
                lines = [f"• {p['title']} — {p.get('currency', 'USD')} {float(p['price']):.2f} ({'in stock' if int(p.get('stock', 0)) > 0 else 'out of stock'})" for p in items]
                reply = "Here are some options:\n" + "\n".join(lines) + "\nWant details on any of these?"
                for p in items:
                    citations.append(f"commerce:product:{p['id']}")
                    result.add_evidence(f"commerce:product:{p['id']}", excerpt=p["title"], source_type="commerce")
            else:
                reply = "I couldn't find a matching product. Could you tell me a bit more about what you need?"
        elif it == "lead":
            lead = {"phone": payload.phone, "name": payload.profile_name, "message": payload.message[:1000], "source": "whatsapp", "status": "new"}
            result.proposed_actions.append(ProposedAction(action_type="crm.create_lead", tool_key="crm.upsert_lead", payload={"lead": {k: v for k, v in lead.items() if v}}, reason="Business inquiry captured from WhatsApp", risk_level="low"))
            lead_captured = True
            reply = "Thanks! I've shared your request with our sales team — they'll reach out shortly. What's the best email to send details to?"
        elif it == "faq":
            hits = services.tools.call("platform.search_knowledge", query=payload.message[:300], collection="kb", limit=2).get("items", [])
            if hits and hits[0]["score"] >= 1.0:
                q = set(tokenize(payload.message))
                best = max(sentences(hits[0]["text"]), key=lambda s: len(q & set(tokenize(s))), default="")
                reply = best[:900] if best else None
                citations.append(hits[0]["ref"])
                result.add_evidence(hits[0]["ref"], excerpt=hits[0]["text"][:160], source_type="knowledge_base")
            if not reply:
                it = "human"
        elif it == "greeting":
            reply = "Hi! ðŸ‘‹ I can help with orders, products and common questions. What can I do for you?"
        if it in {"human", "unknown"}:
            escalated = True
            reply = "Thanks — I'm connecting you with a member of our team who will reply here shortly."
            result.proposed_actions.append(ProposedAction(action_type="helpdesk.create_ticket", tool_key="helpdesk.create_ticket", payload={"subject": f"WhatsApp escalation from …{payload.phone[-4:]}", "description": payload.message[:2000], "customer_id": payload.customer_id, "category": "whatsapp", "priority": "medium", "sla_hours": 4}, reason="Customer needs a human", risk_level="low"))
            result.status = "escalated"

        mode: Literal["session_text", "template", "none"] = "none"
        template_name = None
        if reply and rate_limited:
            result.warnings.append("Per-number rate limit reached; reply held")
            reply_send = False
        else:
            reply_send = bool(reply)
        # Replies inside the customer-initiated service window do not need marketing opt-in;
        # business-initiated templates (outside the window) do.
        if reply_send:
            if within_window:
                mode = "session_text"
                result.proposed_actions.append(ProposedAction(action_type="whatsapp.reply", tool_key="whatsapp.send_text", payload={"to": payload.phone, "text": reply}, reason=f"Reply to {it} within the 24h service window", risk_level="medium", evidence_refs=citations, estimated_minutes_saved=3))
            else:
                templates = [t["name"] for t in services.tools.call("whatsapp.list_templates").get("items", [])]
                template_name = "support_followup" if "support_followup" in templates else (templates[0] if templates else None)
                if template_name and opted_in:
                    mode = "template"
                    result.proposed_actions.append(ProposedAction(action_type="whatsapp.template", tool_key="whatsapp.send_template", payload={"to": payload.phone, "template_name": template_name, "parameters": [payload.profile_name or "there"]}, reason="Outside 24h window: approved template only", risk_level="high"))
                else:
                    result.warnings.append("Outside 24h window and no approved template / opt-in; no message sent")
        result.data = WhatsAppOut(intent=it, reply_text=reply, reply_mode=mode, template_name=template_name, within_24h_window=within_window, opted_in=opted_in, lead_captured=lead_captured, escalated=escalated, citations=citations, rate_limited=rate_limited).model_dump()
        result.summary = f"WhatsApp {it.replace('_', ' ')} handled" + (" · escalated" if escalated else "") + (" · lead captured" if lead_captured else "") + (f" · reply via {mode}" if mode != "none" else "")
        result.confidence = intent.confidence
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved
        return result


Any  # noqa: B018
