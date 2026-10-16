"""Agent 12 - Product Listing.

Generates titles, descriptions, specs, FAQs and SEO metadata from verified
product attributes only, detects missing/inconsistent catalog data, validates
against brand guidelines and prohibited claims, and publishes only through an
approval-gated action.
"""

from __future__ import annotations

import re
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
from app.agents.registry import register
from app.agents.services import AgentServices

COLORS = {"red", "blue", "green", "black", "white", "grey", "gray", "silver", "gold", "pink", "purple", "yellow", "orange", "brown", "navy", "beige"}


class ListingIn(AgentInput):
    product_id: str
    channel: str = "webstore"
    include_faq: bool = True
    publish: bool = True


class FAQ(BaseModel):
    question: str
    answer: str


class ListingDraft(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)
    description: str
    faq: list[FAQ] = Field(default_factory=list)
    seo_title: str
    seo_description: str
    keywords: list[str] = Field(default_factory=list)


class Issue(BaseModel):
    kind: str
    severity: str
    detail: str


class ListingOut(BaseModel):
    product_id: str
    draft: ListingDraft
    specifications: dict[str, Any]
    issues: list[Issue]
    publishable: bool
    verified_attributes: list[str]


def heuristic_listing(p: dict[str, Any], include_faq: bool) -> ListingDraft:
    specs = p.get("specs") or {}
    brand = p.get("brand") or ""
    title = " ".join(x for x in [brand, p.get("title", "")] if x and x not in p.get("title", "")).strip() or p.get("title", "")
    keyspecs = [f"{k.replace('_', ' ').title()}: {v}" for k, v in list(specs.items())[:5]]
    desc = (p.get("description") or f"{p.get('title')} from {brand or 'our catalog'}.").strip()
    faq = []
    if include_faq:
        for k in ("material", "weight", "dimensions", "warranty", "battery_life", "capacity"):
            if k in specs:
                faq.append(FAQ(question=f"What is the {k.replace('_', ' ')}?", answer=f"{specs[k]}."))
    kws = list(dict.fromkeys([str(p.get("category", "")).lower(), *[str(t).lower() for t in p.get("tags", [])], brand.lower()]))
    return ListingDraft(title=title[:150], bullets=keyspecs, description=desc, faq=faq[:5], seo_title=title[:60], seo_description=(desc[:157] + "...") if len(desc) > 160 else desc, keywords=[k for k in kws if k][:10])


@register
class ProductListingAgent(BaseAgent):
    spec = AgentSpec(
        key="product_listing",
        name="Product Listing Agent",
        department="ecommerce",
        version="1.1.1",
        description="Writes product titles, descriptions, specs, FAQs and SEO metadata strictly from verified attributes and validates them against brand rules before approval-gated publishing.",
        use_cases=["New product listings", "Catalog clean-up", "SEO refresh"],
        input_model=ListingIn,
        output_model=ListingOut,
        allowed_tools=["commerce.get_product", "commerce.brand_guidelines", "commerce.update_listing"],
        permission_scopes=["commerce:read", "commerce:write"],
        policies=["verified_attributes_only", "brand_guidelines", "prohibited_claims", "approved_publishing"],
        approval_rules=[ApprovalRule(action_type="commerce.update_listing", condition="all listing publications")],
        timeout_seconds=60,
        token_budget=6000,
        risk_level="medium",
        baseline_minutes_saved=25,
    )

    def run(self, ctx: AgentContext, payload: ListingIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        p = services.tools.call("commerce.get_product", product_id=payload.product_id)
        rules = services.tools.call("commerce.brand_guidelines")
        result.add_evidence(f"commerce:product:{payload.product_id}", excerpt=p.get("title"), source_type="commerce")
        result.add_evidence("commerce:policy:brand_guidelines", excerpt=f"tone={rules.get('tone')}", source_type="policy")
        specs = dict(p.get("specs") or {})
        issues: list[Issue] = []
        for field in rules.get("required_fields", []):
            if field == "specifications":
                if not specs:
                    issues.append(Issue(kind="missing", severity="high", detail="No specifications on record"))
            elif not p.get(field):
                issues.append(Issue(kind="missing", severity="high", detail=f"Required field '{field}' missing"))
        for k in rules.get("required_specs", []):
            if k not in specs:
                issues.append(Issue(kind="missing", severity="medium", detail=f"Spec '{k}' missing"))
        title_colors = {c for c in COLORS if re.search(rf"\b{c}\b", str(p.get("title", "")).lower())}
        spec_color = str(specs.get("color", "")).lower()
        if title_colors and spec_color and not any(c in spec_color for c in title_colors):
            issues.append(Issue(kind="inconsistent", severity="high", detail=f"Title mentions {', '.join(title_colors)} but spec color is '{spec_color}'"))
        w = str(specs.get("weight", ""))
        if w and not re.search(r"\b(g|kg|lb|lbs|oz)\b", w.lower()):
            issues.append(Issue(kind="inconsistent", severity="low", detail=f"Weight '{w}' has no unit"))

        attrs = "\n".join(f"- {k}: {v}" for k, v in {"title": p.get("title"), "brand": p.get("brand"), "category": p.get("category"), "price": p.get("price"), "existing_description": p.get("description"), **specs}.items() if v)
        draft = services.structured(
            task="listing_generation", schema=ListingDraft,
            system=f"Write an e-commerce listing in a {rules.get('tone', 'clear')} tone using ONLY the attributes provided. Never add features, certifications, numbers or claims that are not in the attributes. Avoid: {', '.join(rules.get('prohibited_claims', []))}. SEO title ≤60 chars, meta description ≤160 chars, title ≤150 chars.",
            user=f"Verified attributes:\n{attrs}\nChannel: {payload.channel}. Include FAQ: {payload.include_faq}",
            heuristic=lambda: heuristic_listing(p, payload.include_faq),
        )
        draft.title, draft.seo_title = draft.title[:150], draft.seo_title[:60]
        if len(draft.seo_description) > 160:
            draft.seo_description = draft.seo_description[:157] + "..."
        text = " ".join([draft.title, draft.description, draft.seo_description, *draft.bullets, *(f.question + " " + f.answer for f in draft.faq)])
        for claim in rules.get("prohibited_claims", []):
            if re.search(r"\b" + re.escape(claim.lower()) + r"\b", text.lower()):
                issues.append(Issue(kind="prohibited_claim", severity="high", detail=f"Generated copy contains prohibited claim '{claim}'"))
        source_numbers = set(re.findall(r"\d+(?:\.\d+)?", attrs))
        bad = sorted({n for n in re.findall(r"\d+(?:\.\d+)?", text) if n not in source_numbers})
        if bad:
            issues.append(Issue(kind="unsupported_claim", severity="high", detail=f"Numbers not present in verified attributes: {', '.join(bad[:8])}"))
            result.warnings.append("Generated copy contained unsupported figures; falling back to attribute-only copy")
            draft = heuristic_listing(p, payload.include_faq)
        publishable = not any(i.severity == "high" for i in issues)
        if payload.publish and publishable:
            result.proposed_actions.append(ProposedAction(action_type="commerce.update_listing", tool_key="commerce.update_listing", payload={"product_id": payload.product_id, "fields": {"listing": draft.model_dump(), "listing_status": "published", "listing_channel": payload.channel}}, reason="Publish validated listing", risk_level="medium", evidence_refs=[f"commerce:product:{payload.product_id}"], estimated_minutes_saved=20))
        elif not publishable:
            result.warnings.append("Listing not publishable until high-severity issues are fixed")
            result.missing_information.extend(i.detail for i in issues if i.kind == "missing")
        result.data = ListingOut(product_id=payload.product_id, draft=draft, specifications=specs, issues=issues, publishable=publishable, verified_attributes=[k for k in ["title", "brand", "category", "price", *specs.keys()] if p.get(k) or k in specs]).model_dump()
        result.summary = f"Listing draft for {p.get('title')}: {len(issues)} issue(s); {'ready for approval' if publishable else 'blocked'}"
        result.confidence = 0.85 if publishable else 0.5
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved
        return result
