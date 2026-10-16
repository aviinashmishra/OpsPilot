"""Agent 6 - Complaint Resolution.

Categorises complaints and determines urgency with configured rules, pulls
case history and the applicable policy, creates a ticket with an SLA, and
recommends resolution steps. Compensation is only ever *recommended* within
policy limits and requires approval; the customer-facing draft never promises
more than policy authorises.
"""

from __future__ import annotations

import re
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
from app.agents.common import contains_any, guard_untrusted, parse_dt
from app.agents.registry import register
from app.agents.services import AgentServices
from app.core.errors import NotFound

CATEGORY_RULES: dict[str, list[str]] = {
    "delivery": ["late", "delay", "never arrived", "not arrived", "shipping", "courier", "tracking", "lost package", "still waiting", "delivery"],
    "product_quality": ["broken", "damaged", "defective", "faulty", "stopped working", "poor quality", "cracked", "wrong size", "wrong item"],
    "billing": ["charged twice", "double charged", "overcharged", "invoice", "billing", "payment", "refund not received", "charge"],
    "service": ["rude", "no response", "ignored", "unhelpful", "waited", "on hold", "support"],
}
URGENT = ["lawyer", "legal", "sue", "lawsuit", "injury", "injured", "fire", "unsafe", "fraud", "chargeback", "press", "twitter", "social media", "regulator", "ombudsman"]
DEFAULT_SLA = {"critical": 4, "high": 8, "medium": 24, "low": 72}
PROMISE = re.compile(r"\b(we will|we'll|i will|i'll)\s+(refund|compensate|credit|replace|reimburse)|\bguarantee", re.I)


class ComplaintIn(AgentInput):
    message: str = Field(min_length=1, max_length=8000)
    customer_id: str | None = None
    channel: str | None = None
    order_id: str | None = None


class Classification(BaseModel):
    category: str
    secondary_categories: list[str] = Field(default_factory=list)
    summary: str = Field(max_length=500)


class ComplaintOut(BaseModel):
    category: str
    secondary_categories: list[str]
    urgency: str
    urgency_reasons: list[str]
    sla_hours: int
    sla_due_at: str
    case_history_count: int
    recent_complaints_30d: int
    applicable_policies: list[dict[str, Any]]
    recommended_steps: list[str]
    compensation_recommendation: dict[str, Any] | None
    draft_response: str
    complaint_summary: str


def heuristic_classify(msg: str) -> Classification:
    scores = {cat: len(contains_any(msg, words)) for cat, words in CATEGORY_RULES.items()}
    ranked = sorted(((s, c) for c, s in scores.items() if s), reverse=True)
    cat = ranked[0][1] if ranked else "general"
    return Classification(category=cat, secondary_categories=[c for _, c in ranked[1:]], summary=msg.strip().split("\n")[0][:300])


@register
class ComplaintResolutionAgent(BaseAgent):
    spec = AgentSpec(
        key="complaint_resolution",
        name="Complaint Resolution Agent",
        department="customer_support",
        version="1.1.0",
        description="Categorises complaints, sets urgency and SLA by rule, retrieves case history and policy, opens tickets and recommends policy-bounded resolutions.",
        use_cases=["Complaint triage", "SLA tracking", "Policy-compliant compensation recommendations"],
        input_model=ComplaintIn,
        output_model=ComplaintOut,
        allowed_tools=["crm.get_customer", "helpdesk.case_history", "helpdesk.get_policies", "commerce.get_order", "helpdesk.create_ticket", "helpdesk.update_ticket"],
        permission_scopes=["crm:read", "helpdesk:read", "helpdesk:write", "commerce:read"],
        policies=["no_unauthorized_compensation", "rule_based_urgency", "sla_tracking"],
        approval_rules=[ApprovalRule(action_type="complaint.compensation", condition="any refund, credit or compensation", required_permission="approvals:decide")],
        timeout_seconds=60,
        token_budget=6000,
        risk_level="medium",
        baseline_minutes_saved=12,
    )

    def run(self, ctx: AgentContext, payload: ComplaintIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        wrapped = guard_untrusted(result, payload.message, "complaint")
        cls = services.structured(
            task="complaint_classification", schema=Classification,
            system=f"Classify a customer complaint into one of: {', '.join(CATEGORY_RULES)} or general. Summarise it factually in one sentence.",
            user=wrapped, heuristic=lambda: heuristic_classify(payload.message), tier="fast",
        )
        if cls.category not in CATEGORY_RULES and cls.category != "general":
            cls = heuristic_classify(payload.message)

        customer: dict[str, Any] = {}
        history: list[dict[str, Any]] = []
        if payload.customer_id:
            try:
                customer = services.tools.call("crm.get_customer", customer_id=payload.customer_id)
                result.add_evidence(f"crm:customer:{payload.customer_id}", excerpt=f"tier={customer.get('tier')}", source_type="crm")
            except NotFound:
                result.warnings.append("Customer not found in CRM")
            history = services.tools.call("helpdesk.case_history", customer_id=payload.customer_id).get("items", [])
            for t in history[:5]:
                result.add_evidence(f"helpdesk:ticket:{t['id']}", excerpt=t.get("subject"), source_type="helpdesk")
        recent = [t for t in history if (parse_dt(t.get("created_at")) or ctx.now) >= ctx.now - timedelta(days=30)]

        order: dict[str, Any] | None = None
        if payload.order_id:
            try:
                order = services.tools.call("commerce.get_order", order_id=payload.order_id)
                result.add_evidence(f"commerce:order:{payload.order_id}", excerpt=f"total={order.get('total')} status={order.get('status')}", source_type="commerce")
            except NotFound:
                result.warnings.append(f"Order {payload.order_id} not found; compensation cannot be assessed")

        # Deterministic urgency rules
        reasons: list[str] = []
        urgent_hits = contains_any(payload.message, URGENT)
        urgency = "medium"
        if urgent_hits:
            urgency = "critical" if any(w in urgent_hits for w in ("injury", "injured", "fire", "unsafe")) else "high"
            reasons.append(f"Escalation keywords: {', '.join(urgent_hits)}")
        if customer.get("tier") in {"vip", "enterprise"}:
            urgency = "high" if urgency in {"medium", "low"} else urgency
            reasons.append(f"Customer tier '{customer.get('tier')}'")
        if len(recent) >= 2:
            urgency = "high" if urgency in {"medium", "low"} else urgency
            reasons.append(f"{len(recent)} complaints in the last 30 days")
        open_tickets = [t for t in history if str(t.get("status", "")).lower() in {"open", "pending"}]
        if open_tickets:
            urgency = "high" if urgency in {"medium", "low"} else urgency
            reasons.append(f"Repeat contact while {len(open_tickets)} ticket(s) still open ({', '.join(t['id'] for t in open_tickets[:3])})")
        if not reasons:
            reasons.append("Standard complaint, no escalation rule matched")
        sla_table = {**DEFAULT_SLA, **(ctx.agent_config.get("sla_hours") or {})}
        sla_hours = int(sla_table[urgency])
        sla_due = ctx.now + timedelta(hours=sla_hours)

        policies = services.tools.call("helpdesk.get_policies", topic=cls.category).get("items", [])
        if not policies:
            policies = services.tools.call("helpdesk.get_policies").get("items", [])
            policies = [p for p in policies if p.get("topic") in {cls.category, "general"}]
        for p in policies:
            result.add_evidence(f"policy:{p['id']}#{p.get('section', '')}", excerpt=p.get("text", "")[:200], source_type="policy")

        steps = ["Acknowledge the complaint and confirm the SLA to the customer"]
        compensation = None
        for p in policies:
            steps.extend(p.get("resolution_steps", []))
            comp = p.get("compensation")
            if comp and order:
                cap = float(comp.get("max_pct_of_order", 0)) / 100 * float(order.get("total") or 0)
                cap = min(cap, float(comp.get("max_amount", cap)))
                compensation = {"type": comp.get("type", "credit"), "max_amount": round(cap, 2), "currency": order.get("currency", "USD"), "policy_ref": f"policy:{p['id']}#{p.get('section', '')}", "conditions": comp.get("conditions"), "status": "recommendation_requires_approval"}
        if compensation is None and any(p.get("compensation") for p in policies):
            result.missing_information.append("Order details are required to assess policy-based compensation")
        steps = list(dict.fromkeys(steps))

        first = (customer.get("name") or "there").split()[0]
        draft = (
            f"Hi {first},\n\nThank you for telling us about this, and I'm sorry for the experience. "
            f"I've logged your complaint as a {cls.category.replace('_', ' ')} issue and a specialist will respond within {sla_hours} hours. "
            "We'll review it against our policy and keep you updated on the next steps.\n\nKind regards,\nCustomer Care"
        )
        if PROMISE.search(draft):  # defensive - draft must never promise compensation
            draft = PROMISE.sub("review", draft)

        ticket_payload = {
            "subject": f"[{urgency.upper()}] {cls.category.replace('_', ' ').title()} complaint: {cls.summary[:80]}",
            "description": f"{cls.summary}\n\nUrgency reasons: {'; '.join(reasons)}\nRecommended steps:\n- " + "\n- ".join(steps) + f"\n\nOriginal message:\n{payload.message[:2000]}",
            "customer_id": payload.customer_id, "category": cls.category, "priority": urgency, "sla_hours": sla_hours, "order_id": payload.order_id,
        }
        result.proposed_actions.append(ProposedAction(action_type="helpdesk.create_ticket", tool_key="helpdesk.create_ticket", payload=ticket_payload, reason=f"Open {urgency} complaint ticket with {sla_hours}h SLA", risk_level="low", evidence_refs=result.evidence_refs[:3], estimated_minutes_saved=8))
        if compensation:
            result.proposed_actions.append(ProposedAction(
                action_type="complaint.compensation", tool_key="helpdesk.create_ticket",
                payload={"subject": f"Compensation review: up to {compensation['currency']} {compensation['max_amount']:.2f} ({compensation['type']})", "description": f"Policy {compensation['policy_ref']} allows up to {compensation['max_amount']:.2f}. Conditions: {compensation.get('conditions')}. Approve to open a compensation case for fulfilment.", "customer_id": payload.customer_id, "category": "compensation", "priority": urgency, "amount": compensation["max_amount"]},
                reason="Policy-bounded compensation recommendation (not promised to customer)", risk_level="high", requires_approval=True, evidence_refs=[compensation["policy_ref"]],
            ))
        result.data = ComplaintOut(
            category=cls.category, secondary_categories=cls.secondary_categories, urgency=urgency, urgency_reasons=reasons, sla_hours=sla_hours, sla_due_at=sla_due.isoformat(),
            case_history_count=len(history), recent_complaints_30d=len(recent),
            applicable_policies=[{"id": p["id"], "section": p.get("section"), "title": p.get("title")} for p in policies],
            recommended_steps=steps, compensation_recommendation=compensation, draft_response=draft, complaint_summary=cls.summary,
        ).model_dump()
        result.summary = f"{urgency.title()} {cls.category} complaint · SLA {sla_hours}h · {len(policies)} policy section(s) applied" + (" · compensation recommendation pending approval" if compensation else "")
        result.confidence = 0.85 if cls.category != "general" else 0.6
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved
        return result
