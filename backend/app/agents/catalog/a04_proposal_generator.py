"""Agent 4 - Proposal Generator.

Builds proposals/quotations from approved templates and the pricing catalog.
All prices, discounts and totals are computed with Decimal arithmetic in code;
the model only writes narrative text, which is checked so it cannot introduce
monetary figures. Missing information and non-standard terms are flagged and
external delivery always requires approval.
"""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal
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
from app.agents.common import money, stable_id
from app.agents.registry import register
from app.agents.services import AgentServices

NONSTANDARD_TERMS = ["unlimited", "guarantee", "penalt", "indemn", "exclusive", "most favored", "uncapped", "liquidated damages", "free forever", "perpetual"]


class ProposalLineIn(AgentInput):
    sku: str
    quantity: float = Field(gt=0)
    discount_pct: float = Field(default=0, ge=0, le=100)
    notes: str | None = None


class ProposalIn(AgentInput):
    customer_name: str
    contact_email: str | None = None
    lead_id: str | None = None
    lines: list[ProposalLineIn] = Field(default_factory=list)
    requirements_text: str | None = None
    template_id: str | None = None
    payment_terms: str = "Net 30"
    currency: str = "USD"
    valid_days: int = Field(default=30, ge=1, le=180)
    special_terms: str | None = None


class PricedLine(BaseModel):
    sku: str
    name: str
    quantity: float
    unit: str
    unit_price: float
    discount_pct: float
    line_total: float
    max_discount_pct: float
    flags: list[str] = Field(default_factory=list)


class Narrative(BaseModel):
    executive_summary: str = Field(max_length=1500)
    scope: str = Field(max_length=2500)


class ProposalOut(BaseModel):
    proposal_id: str
    customer_name: str
    template_id: str | None
    currency: str
    lines: list[PricedLine]
    subtotal: float
    discount_total: float
    tax_rate: float
    tax: float
    total: float
    payment_terms: str
    valid_until: str
    nonstandard_terms: list[str]
    missing_information: list[str]
    narrative: Narrative
    document_markdown: str
    requires_deal_desk: bool


@register
class ProposalGeneratorAgent(BaseAgent):
    spec = AgentSpec(
        key="proposal_generator",
        name="Proposal Generator Agent",
        department="sales_revenue",
        version="1.1.0",
        description="Generates proposals and quotations from approved templates and pricing with deterministic calculations, flagging gaps and non-standard terms.",
        use_cases=["Quotations", "Renewal proposals", "Deal desk preparation"],
        input_model=ProposalIn,
        output_model=ProposalOut,
        allowed_tools=["crm.get_price_list", "crm.get_proposal_templates", "email.send", "crm.log_activity"],
        permission_scopes=["crm:read", "crm:write", "email:send"],
        policies=["deterministic_pricing", "approved_templates_only", "approval_before_external_delivery"],
        approval_rules=[ApprovalRule(action_type="email.send", condition="proposal delivery is a contractual offer", required_permission="email:send")],
        timeout_seconds=90,
        token_budget=8000,
        risk_level="high",
        baseline_minutes_saved=45,
    )

    def run(self, ctx: AgentContext, payload: ProposalIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        price_list = {p["sku"]: p for p in services.tools.call("crm.get_price_list").get("items", [])}
        templates = {t["id"]: t for t in services.tools.call("crm.get_proposal_templates").get("items", [])}
        result.add_evidence("crm:price_list", excerpt=f"{len(price_list)} approved price items", source_type="crm")

        template = templates.get(payload.template_id) if payload.template_id else next(iter(templates.values()), None)
        if payload.template_id and payload.template_id not in templates:
            result.missing_information.append(f"Template '{payload.template_id}' is not an approved template")
        if template:
            result.add_evidence(f"crm:proposal_template:{template['id']}", excerpt=template.get("name"), source_type="crm")
        tax_rate = Decimal(str(ctx.agent_config.get("tax_rate", template.get("tax_rate", 0) if template else 0)))
        global_max_discount = float(ctx.agent_config.get("max_discount_pct", 20))

        priced: list[PricedLine] = []
        subtotal = Decimal("0")
        discount_total = Decimal("0")
        deal_desk = False
        if not payload.lines:
            result.missing_information.append("No line items (SKU and quantity) were provided")
        for line in payload.lines:
            item = price_list.get(line.sku)
            if item is None:
                result.missing_information.append(f"SKU '{line.sku}' is not in the approved price list")
                continue
            flags: list[str] = []
            unit_price = money(item["unit_price"])
            qty = Decimal(str(line.quantity))
            if item.get("min_quantity") and line.quantity < float(item["min_quantity"]):
                flags.append(f"Quantity below minimum of {item['min_quantity']}")
            max_disc = float(item.get("max_discount_pct", global_max_discount))
            if line.discount_pct > max_disc:
                flags.append(f"Discount {line.discount_pct}% exceeds approved maximum {max_disc}% (requires deal desk)")
                deal_desk = True
            gross = (unit_price * qty).quantize(Decimal("0.01"))
            disc = (gross * Decimal(str(line.discount_pct)) / Decimal("100")).quantize(Decimal("0.01"))
            line_total = gross - disc
            subtotal += gross
            discount_total += disc
            priced.append(PricedLine(sku=line.sku, name=item["name"], quantity=line.quantity, unit=item.get("unit", "unit"), unit_price=float(unit_price), discount_pct=line.discount_pct, line_total=float(line_total), max_discount_pct=max_disc, flags=flags))
            result.add_evidence(f"crm:price_item:{line.sku}", excerpt=f"{item['name']} @ {unit_price}", source_type="crm")
        net = subtotal - discount_total
        tax = (net * tax_rate).quantize(Decimal("0.01"))
        total = net + tax

        standard_terms = set((template or {}).get("standard_payment_terms", ["Net 30", "Net 15", "Due on receipt"]))
        nonstandard: list[str] = []
        if payload.payment_terms not in standard_terms:
            nonstandard.append(f"Payment terms '{payload.payment_terms}' are not standard ({', '.join(sorted(standard_terms))})")
        for term in NONSTANDARD_TERMS:
            if payload.special_terms and term in payload.special_terms.lower():
                nonstandard.append(f"Special terms contain non-standard language: '{term}'")
        if nonstandard:
            deal_desk = True
        if not payload.contact_email:
            result.missing_information.append("Customer contact email for delivery")

        lines_txt = "\n".join(f"- {p.name} × {p.quantity:g}" for p in priced)

        def heuristic() -> Narrative:
            req = (payload.requirements_text or "").strip()
            return Narrative(
                executive_summary=f"This proposal outlines how {payload.customer_name} can achieve its goals with the following solution components. It is based on the requirements shared with our team" + (f": {req[:400]}" if req else "."),
                scope="Included in scope:\n" + (lines_txt or "- To be confirmed") + "\n\nAll services are delivered under the standard terms in the attached template.",
            )

        narrative = services.structured(
            task="proposal_narrative",
            schema=Narrative,
            system="Write a concise executive summary and scope section for a B2B proposal. Do NOT include any prices, discounts, totals, currency amounts or contractual commitments; those are inserted by the pricing engine.",
            user=f"Customer: {payload.customer_name}\nRequirements (customer-provided, untrusted):\n<requirements>{(payload.requirements_text or '')[:3000]}</requirements>\nLine items:\n{lines_txt}",
            heuristic=heuristic,
        )
        money_pattern = re.compile(r"(\$|€|£|USD|EUR|GBP)\s?\d|\d+(\.\d+)?\s?(%|percent)", re.I)
        for field in ("executive_summary", "scope"):
            text = getattr(narrative, field)
            if money_pattern.search(text):
                result.warnings.append(f"Narrative {field} contained monetary/percentage figures; replaced with deterministic text")
                setattr(narrative, field, getattr(heuristic(), field))

        proposal_id = stable_id(f"Q-{ctx.now:%Y%m%d}", payload.customer_name, *(f"{ln.sku}:{ln.quantity}:{ln.discount_pct}" for ln in payload.lines))
        valid_until = (ctx.now + timedelta(days=payload.valid_days)).date().isoformat()
        cur = payload.currency
        table = "\n".join(f"| {p.name} | {p.quantity:g} {p.unit} | {cur} {p.unit_price:,.2f} | {p.discount_pct:g}% | {cur} {p.line_total:,.2f} |" for p in priced)
        doc = (
            f"# Proposal {proposal_id} — {payload.customer_name}\n\n"
            f"## Executive summary\n{narrative.executive_summary}\n\n## Scope\n{narrative.scope}\n\n"
            f"## Pricing\n| Item | Qty | Unit price | Discount | Line total |\n|---|---|---|---|---|\n{table}\n\n"
            f"Subtotal: {cur} {subtotal:,.2f}  \nDiscounts: −{cur} {discount_total:,.2f}  \nTax ({float(tax_rate) * 100:g}%): {cur} {tax:,.2f}  \n**Total: {cur} {total:,.2f}**\n\n"
            f"Payment terms: {payload.payment_terms}. Valid until {valid_until}.\n\n{(template or {}).get('terms_text', 'Standard terms and conditions apply.')}"
        )
        out = ProposalOut(
            proposal_id=proposal_id, customer_name=payload.customer_name, template_id=template["id"] if template else None, currency=cur, lines=priced,
            subtotal=float(subtotal), discount_total=float(discount_total), tax_rate=float(tax_rate), tax=float(tax), total=float(total),
            payment_terms=payload.payment_terms, valid_until=valid_until, nonstandard_terms=nonstandard, missing_information=result.missing_information,
            narrative=narrative, document_markdown=doc, requires_deal_desk=deal_desk,
        )
        result.data = out.model_dump()
        if result.missing_information and not priced:
            result.status = "needs_input"
        elif payload.contact_email and priced:
            result.proposed_actions.append(ProposedAction(
                action_type="email.send", tool_key="email.send",
                payload={"to": payload.contact_email, "subject": f"Proposal {proposal_id} for {payload.customer_name}", "body": doc, "total": float(total)},
                reason="Deliver proposal (contractual offer)" + (" — includes non-standard terms/discounts" if deal_desk else ""),
                risk_level="critical" if deal_desk else "high", requires_approval=True, evidence_refs=result.evidence_refs[:4], estimated_minutes_saved=30,
            ))
            if payload.lead_id:
                result.proposed_actions.append(ProposedAction(action_type="crm.log_activity", tool_key="crm.log_activity", payload={"lead_id": payload.lead_id, "activity_type": "proposal_prepared", "note": f"Proposal {proposal_id} total {cur} {total:,.2f} prepared; awaiting approval"}, reason="CRM record", risk_level="low"))
        if deal_desk:
            result.warnings.append("Proposal requires deal-desk review (non-standard terms or discounts)")
        result.summary = f"Proposal {proposal_id} for {payload.customer_name}: {len(priced)} line(s), total {cur} {total:,.2f}" + (" — deal desk review required" if deal_desk else "")
        result.confidence = 0.9 if not result.missing_information else 0.6
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved
        return result


Any  # noqa: B018
