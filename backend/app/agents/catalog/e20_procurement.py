"""Agent 20 - Procurement.

Normalises supplier quotations for an RFQ (currency, units, landed cost),
scores them on approved weighted criteria, explains trade-offs, detects missing
data and policy conflicts, and recommends a supplier. Issuing a purchase order
is a critical-risk action that always requires approval.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentResult, AgentSpec, BaseAgent, ProposedAction
from app.agents.common import money
from app.agents.registry import register
from app.agents.services import AgentServices

DEFAULT_WEIGHTS = {"price": 0.45, "lead_time": 0.2, "quality": 0.2, "terms": 0.15}


class ProcurementIn(AgentInput):
    rfq_id: str
    weights: dict[str, float] | None = None
    fx_rates: dict[str, float] = Field(default_factory=dict, description="Rates to the RFQ currency, e.g. {'EUR': 1.08}")


class NormalizedQuote(BaseModel):
    quote_id: str
    supplier_id: str
    supplier_name: str | None
    approved_supplier: bool
    unit_price_normalized: float | None
    landed_total: float | None
    currency: str
    lead_time_days: int | None
    payment_terms: str | None
    warranty_months: int | None
    quality_rating: float | None
    missing_fields: list[str]
    policy_conflicts: list[str]
    score: float | None
    score_breakdown: dict[str, float]


class ProcurementOut(BaseModel):
    rfq_id: str
    quotes: list[NormalizedQuote]
    recommended_quote_id: str | None
    recommendation: str
    trade_offs: list[str]
    policy: dict[str, Any]
    quotes_required: int
    quotes_received: int


@register
class ProcurementAgent(BaseAgent):
    spec = AgentSpec(
        key="procurement",
        name="Procurement Agent",
        department="finance_admin",
        version="1.0.2",
        description="Normalises and compares supplier quotes on approved criteria, explains trade-offs, flags policy conflicts and recommends a supplier; POs always require approval.",
        use_cases=["RFQ evaluation", "Supplier selection memo", "PO preparation"],
        input_model=ProcurementIn,
        output_model=ProcurementOut,
        allowed_tools=["procurement.get_rfq", "procurement.list_quotes", "procurement.get_supplier", "procurement.get_policy", "procurement.create_purchase_order", "platform.create_task"],
        permission_scopes=["procurement:read", "procurement:commit", "tasks:write"],
        policies=["approved_criteria_only", "policy_conflict_detection", "po_requires_approval"],
        timeout_seconds=90,
        token_budget=4000,
        risk_level="critical",
        baseline_minutes_saved=50,
    )

    def run(self, ctx: AgentContext, payload: ProcurementIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        rfq = services.tools.call("procurement.get_rfq", rfq_id=payload.rfq_id)
        policy = services.tools.call("procurement.get_policy")
        quotes = services.tools.call("procurement.list_quotes", rfq_id=payload.rfq_id).get("items", [])
        result.add_evidence(f"procurement:rfq:{payload.rfq_id}", excerpt=f"{rfq.get('item')} × {rfq.get('quantity')}", source_type="procurement")
        result.add_evidence("policy:procurement", excerpt=f"min_quotes={policy.get('min_quotes')}", source_type="policy")
        qty = float(rfq.get("quantity") or 1)
        cur = rfq.get("currency", "USD")
        weights = {**DEFAULT_WEIGHTS, **(payload.weights or ctx.agent_config.get("weights") or {})}
        req_fields = policy.get("required_fields", [])
        normalized: list[NormalizedQuote] = []
        for q in quotes:
            sup = services.tools.call("procurement.get_supplier", supplier_id=q["supplier_id"]) if q.get("supplier_id") else {}
            result.add_evidence(f"procurement:quote:{q['id']}", excerpt=f"{sup.get('name')} {q.get('unit_price')} {q.get('currency')}", source_type="procurement")
            missing = [f for f in req_fields if q.get(f) in (None, "")]
            conflicts: list[str] = []
            approved = bool(sup.get("approved"))
            if policy.get("approved_suppliers_only") and not approved:
                conflicts.append("Supplier is not on the approved list")
            if sup.get("status") == "suspended":
                conflicts.append("Supplier is suspended")
            price = q.get("unit_price")
            qcur = q.get("currency", cur)
            unit = None
            if price is not None:
                rate = 1.0 if qcur == cur else payload.fx_rates.get(qcur)
                if rate is None:
                    missing.append(f"fx_rate:{qcur}")
                else:
                    per = float(q.get("pack_size") or 1)
                    unit = float(price) * rate / per
            landed = None
            if unit is not None:
                landed = float(money(unit * qty + float(q.get("shipping_cost") or 0) * (1.0 if qcur == cur else payload.fx_rates.get(qcur, 1.0)) + float(q.get("duties") or 0)))
                if policy.get("max_single_approval") and landed > float(policy["max_single_approval"]):
                    conflicts.append(f"Total {landed:,.2f} exceeds single-approval limit {policy['max_single_approval']:,} (board/second approver required)")
            if rfq.get("required_by_days") and q.get("lead_time_days") and int(q["lead_time_days"]) > int(rfq["required_by_days"]):
                conflicts.append(f"Lead time {q['lead_time_days']}d exceeds required {rfq['required_by_days']}d")
            normalized.append(NormalizedQuote(quote_id=q["id"], supplier_id=q.get("supplier_id", "?"), supplier_name=sup.get("name"), approved_supplier=approved, unit_price_normalized=round(unit, 4) if unit is not None else None, landed_total=landed, currency=cur, lead_time_days=q.get("lead_time_days"), payment_terms=q.get("payment_terms"), warranty_months=q.get("warranty_months"), quality_rating=sup.get("quality_rating"), missing_fields=missing, policy_conflicts=conflicts, score=None, score_breakdown={}))
        comparable = [n for n in normalized if n.landed_total is not None and not n.policy_conflicts]
        if comparable:
            lo, hi = min(n.landed_total for n in comparable), max(n.landed_total for n in comparable)  # type: ignore[type-var]
            lts = [n.lead_time_days for n in comparable if n.lead_time_days is not None]
            lt_lo, lt_hi = (min(lts), max(lts)) if lts else (0, 0)
            for n in comparable:
                bd = {"price": 1.0 if hi == lo else 1 - (n.landed_total - lo) / (hi - lo)}  # type: ignore[operator]
                bd["lead_time"] = 0.5 if n.lead_time_days is None else (1.0 if lt_hi == lt_lo else 1 - (n.lead_time_days - lt_lo) / (lt_hi - lt_lo))
                bd["quality"] = (n.quality_rating or 3.0) / 5.0
                terms = (n.payment_terms or "").lower()
                bd["terms"] = 1.0 if "60" in terms else 0.8 if "45" in terms else 0.6 if "30" in terms else 0.3
                if n.warranty_months:
                    bd["terms"] = min(1.0, bd["terms"] + n.warranty_months / 120)
                n.score_breakdown = {k: round(v, 3) for k, v in bd.items()}
                n.score = round(sum(weights[k] * bd[k] for k in bd), 4)
        ranked = sorted(comparable, key=lambda n: -(n.score or 0))
        trade_offs: list[str] = []
        if len(ranked) >= 2:
            a, b = ranked[0], ranked[1]
            if a.landed_total and b.landed_total and a.landed_total > b.landed_total:
                trade_offs.append(f"{a.supplier_name} costs {a.landed_total - b.landed_total:,.2f} more than {b.supplier_name} but scores higher on " + ", ".join(k for k in a.score_breakdown if a.score_breakdown[k] > b.score_breakdown.get(k, 0)))
            if a.lead_time_days and b.lead_time_days and a.lead_time_days > b.lead_time_days:
                trade_offs.append(f"{b.supplier_name} delivers {a.lead_time_days - b.lead_time_days} days sooner")
        for n in normalized:
            if n.policy_conflicts:
                trade_offs.append(f"{n.supplier_name or n.supplier_id} excluded: " + "; ".join(n.policy_conflicts))
        min_q = int(policy.get("min_quotes", 3))
        if len(quotes) < min_q:
            result.missing_information.append(f"Policy requires {min_q} quotes; {len(quotes)} received")
        for n in normalized:
            for m in n.missing_fields:
                result.missing_information.append(f"{n.supplier_name or n.supplier_id}: {m}")
        best = ranked[0] if ranked else None
        if best and len(quotes) >= min_q:
            rec = f"Recommend {best.supplier_name} (score {best.score:.2f}, landed {cur} {best.landed_total:,.2f}, lead time {best.lead_time_days}d)"
            lines = [{"item": rfq.get("item"), "quantity": qty, "unit_price": best.unit_price_normalized}]
            result.proposed_actions.append(ProposedAction(action_type="procurement.purchase_order", tool_key="procurement.create_purchase_order", payload={"supplier_id": best.supplier_id, "rfq_id": payload.rfq_id, "lines": lines, "total": best.landed_total}, reason=rec, risk_level="critical", evidence_refs=[f"procurement:quote:{best.quote_id}", "policy:procurement"], estimated_minutes_saved=30))
        elif best:
            rec = f"Preferred quote is {best.supplier_name}, but policy requires {min_q} quotes before commitment"
            result.status = "needs_input"
        else:
            rec = "No policy-compliant, comparable quote; obtain missing data or additional quotes"
            result.status = "needs_input"
        result.proposed_actions.append(ProposedAction(action_type="platform.create_task", tool_key="platform.create_task", payload={"title": f"Procurement decision: RFQ {payload.rfq_id}", "description": rec + "\n\nTrade-offs:\n- " + "\n- ".join(trade_offs or ["none"]), "priority": "medium", "labels": ["procurement"], "evidence_refs": result.evidence_refs[:6]}, reason="Record recommendation for the buyer", risk_level="low"))
        result.data = ProcurementOut(rfq_id=payload.rfq_id, quotes=normalized, recommended_quote_id=best.quote_id if best else None, recommendation=rec, trade_offs=trade_offs, policy={k: policy.get(k) for k in ("min_quotes", "approved_suppliers_only", "max_single_approval")}, quotes_required=min_q, quotes_received=len(quotes)).model_dump()
        result.summary = f"RFQ {payload.rfq_id}: {len(quotes)} quote(s), {len(comparable)} comparable. {rec}"
        result.confidence = 0.85 if best and len(quotes) >= min_q else 0.5
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved if quotes else 0
        return result
