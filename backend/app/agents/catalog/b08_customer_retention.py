"""Agent 8 - Customer Retention.

Flags inactive / at-risk customers from approved business data with explicit,
evidence-backed signals; never infers sensitive traits. Recommends
interventions that respect consent; outreach campaigns are drafted, never sent
automatically.
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
from app.agents.common import parse_dt, strip_protected
from app.agents.registry import register
from app.agents.services import AgentServices

WEIGHTS = {"inactivity": 35, "order_decline": 20, "usage_drop": 20, "support_issues": 15, "low_nps": 10}


class RetentionIn(AgentInput):
    customer_ids: list[str] | None = None
    segment: str | None = None
    inactivity_days: int = Field(default=60, ge=7, le=730)
    risk_threshold: float = Field(default=40, ge=0, le=100)
    max_customers: int = Field(default=200, ge=1, le=2000)


class RiskSignal(BaseModel):
    signal: str
    points: float
    detail: str
    evidence_ref: str


class AtRiskCustomer(BaseModel):
    customer_id: str
    name: str | None
    risk_score: float
    risk_level: str
    signals: list[RiskSignal]
    explanation: str
    recommended_interventions: list[str]
    outreach_allowed: bool
    consent_basis: str


class RetentionOut(BaseModel):
    evaluated: int
    at_risk: list[AtRiskCustomer]
    excluded_sensitive_fields: list[str]
    campaign_draft: dict[str, Any] | None = None
    method: str


@register
class CustomerRetentionAgent(BaseAgent):
    spec = AgentSpec(
        key="customer_retention",
        name="Customer Retention Agent",
        department="customer_support",
        version="1.0.1",
        description="Identifies inactive or at-risk customers with transparent evidence and recommends consent-aware retention interventions.",
        use_cases=["Churn risk review", "Win-back campaign drafting", "Account manager prioritisation"],
        input_model=RetentionIn,
        output_model=RetentionOut,
        allowed_tools=["crm.list_customers", "crm.get_customer", "crm.check_consent", "helpdesk.case_history", "platform.create_task"],
        permission_scopes=["crm:read", "helpdesk:read", "tasks:write"],
        policies=["no_sensitive_trait_inference", "consent_respected", "no_auto_campaigns"],
        approval_rules=[ApprovalRule(action_type="email.send", condition="campaigns are never auto-sent")],
        timeout_seconds=120,
        token_budget=6000,
        risk_level="medium",
        baseline_minutes_saved=30,
    )

    def run(self, ctx: AgentContext, payload: RetentionIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        if payload.customer_ids:
            customers = []
            for cid in payload.customer_ids[: payload.max_customers]:
                try:
                    customers.append(services.tools.call("crm.get_customer", customer_id=cid))
                except Exception:  # noqa: BLE001
                    result.warnings.append(f"Customer {cid} not found")
        else:
            customers = services.tools.call("crm.list_customers", segment=payload.segment, limit=payload.max_customers).get("items", [])
        excluded: set[str] = set()
        at_risk: list[AtRiskCustomer] = []
        for raw in customers:
            c, removed = strip_protected(raw)
            excluded.update(removed)
            cid = str(c.get("id"))
            ref = f"crm:customer:{cid}"
            signals: list[RiskSignal] = []
            last = parse_dt(c.get("last_order_at"))
            if last:
                idle = (ctx.now - last).days
                if idle >= payload.inactivity_days:
                    pts = min(WEIGHTS["inactivity"], WEIGHTS["inactivity"] * idle / (payload.inactivity_days * 2))
                    signals.append(RiskSignal(signal="inactivity", points=round(pts, 1), detail=f"No order for {idle} days (threshold {payload.inactivity_days})", evidence_ref=f"{ref}:last_order_at"))
            prev, cur = c.get("orders_prev_90d"), c.get("orders_last_90d")
            if isinstance(prev, int | float) and isinstance(cur, int | float) and prev > 0 and cur < prev:
                drop = (prev - cur) / prev
                if drop >= 0.3:
                    signals.append(RiskSignal(signal="order_decline", points=round(WEIGHTS["order_decline"] * min(1, drop), 1), detail=f"Orders fell {drop:.0%} ({prev} → {cur}) vs prior 90 days", evidence_ref=f"{ref}:orders_last_90d"))
            usage = c.get("usage_change_pct")
            if isinstance(usage, int | float) and usage <= -25:
                signals.append(RiskSignal(signal="usage_drop", points=round(WEIGHTS["usage_drop"] * min(1, abs(usage) / 60), 1), detail=f"Product usage changed {usage:+.0f}% over 30 days", evidence_ref=f"{ref}:usage_change_pct"))
            open_tickets = int(c.get("open_tickets") or 0)
            complaints = int(c.get("complaints_90d") or 0)
            if open_tickets + complaints >= 2:
                signals.append(RiskSignal(signal="support_issues", points=round(min(WEIGHTS["support_issues"], 5 * (open_tickets + complaints)), 1), detail=f"{open_tickets} open ticket(s), {complaints} complaint(s) in 90 days", evidence_ref=f"{ref}:open_tickets"))
            nps = c.get("last_nps")
            if isinstance(nps, int | float) and nps <= 6:
                signals.append(RiskSignal(signal="low_nps", points=WEIGHTS["low_nps"] if nps <= 4 else WEIGHTS["low_nps"] / 2, detail=f"Last NPS response {nps}/10 (customer-provided)", evidence_ref=f"{ref}:last_nps"))
            score = round(sum(s.points for s in signals), 1)
            if score < payload.risk_threshold:
                continue
            level = "high" if score >= 70 else "medium" if score >= 50 else "watch"
            consent = services.tools.call("crm.check_consent", email=c.get("email")) if c.get("email") else {"found": False}
            outreach = bool(consent.get("marketing_opt_in")) and not consent.get("unsubscribed") and not consent.get("do_not_contact")
            basis = "marketing opt-in on record" if outreach else ("unsubscribed / do-not-contact" if consent.get("unsubscribed") or consent.get("do_not_contact") else "no marketing consent on record")
            interventions: list[str] = []
            kinds = {s.signal for s in signals}
            if "support_issues" in kinds:
                interventions.append("Service recovery: account manager reviews open issues and calls the customer")
            if "usage_drop" in kinds:
                interventions.append("Offer a product training / onboarding session")
            if "inactivity" in kinds or "order_decline" in kinds:
                interventions.append("Win-back offer (email draft — requires approval)" if outreach else "Account manager check-in (no marketing outreach: consent not on record)")
            if (c.get("lifetime_value") or 0) >= float(ctx.agent_config.get("high_value_ltv", 10000)):
                interventions.insert(0, "High-value account: executive sponsor outreach")
            explanation = "; ".join(s.detail for s in signals)
            for s in signals:
                result.add_evidence(s.evidence_ref, excerpt=s.detail, source_type="crm")
            at_risk.append(AtRiskCustomer(customer_id=cid, name=c.get("name"), risk_score=score, risk_level=level, signals=signals, explanation=explanation, recommended_interventions=interventions, outreach_allowed=outreach, consent_basis=basis))

        at_risk.sort(key=lambda a: -a.risk_score)
        for a in at_risk:
            if a.risk_level == "high" or (a.risk_level == "medium" and len(at_risk) <= 10):
                result.proposed_actions.append(ProposedAction(
                    action_type="platform.create_task", tool_key="platform.create_task",
                    payload={"title": f"Retention: {a.name or a.customer_id} ({a.risk_level} risk, {a.risk_score:.0f})", "description": f"Signals: {a.explanation}\nRecommended: " + "; ".join(a.recommended_interventions) + f"\nConsent: {a.consent_basis}", "priority": "high" if a.risk_level == "high" else "medium", "labels": ["retention", a.risk_level], "evidence_refs": [s.evidence_ref for s in a.signals]},
                    reason="Account manager follow-up for at-risk customer", risk_level="low", evidence_refs=[s.evidence_ref for s in a.signals], estimated_minutes_saved=5,
                ))
        eligible = [a for a in at_risk if a.outreach_allowed]
        campaign = None
        if eligible:
            campaign = {"status": "draft_not_sent", "audience_size": len(eligible), "audience": [a.customer_id for a in eligible], "subject": "We'd love to have you back", "body": "Hi {first_name},\n\nIt's been a while! Here's what's new since your last visit... (offer subject to approval)", "note": "Campaigns are never sent automatically; route through the approval center."}
        if excluded:
            result.warnings.append(f"Sensitive fields ignored: {', '.join(sorted(excluded))}")
        result.data = RetentionOut(evaluated=len(customers), at_risk=at_risk, excluded_sensitive_fields=sorted(excluded), campaign_draft=campaign, method="Weighted, rule-based signals on approved CRM fields: " + ", ".join(f"{k}≤{v}pts" for k, v in WEIGHTS.items())).model_dump()
        result.summary = f"{len(at_risk)} of {len(customers)} customers at risk ({sum(1 for a in at_risk if a.risk_level == 'high')} high)"
        result.confidence = 0.8
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved if customers else 0
        return result
