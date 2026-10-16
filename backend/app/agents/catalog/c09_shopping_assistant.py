"""Agent 9 - AI Shopping Assistant.

Understands needs and budget, searches the verified catalog, compares specs and
recommends products with current price/stock from the authoritative commerce
API. It can prepare a draft cart; it never checks out or purchases.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentResult, AgentSpec, BaseAgent, ProposedAction
from app.agents.common import guard_untrusted, to_float, tokenize
from app.agents.registry import register
from app.agents.services import AgentServices
from app.core.errors import NotFound


class CartLine(BaseModel):
    product_id: str
    quantity: int = Field(default=1, ge=1, le=50)


class ShopIn(AgentInput):
    query: str = Field(min_length=2, max_length=2000)
    budget_max: float | None = Field(default=None, gt=0)
    category: str | None = None
    must_have: list[str] = Field(default_factory=list)
    customer_id: str | None = None
    add_to_cart: list[CartLine] = Field(default_factory=list)
    confirm_checkout: bool = False


class Needs(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    budget_max: float | None = None
    category: str | None = None
    must_have: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    product_id: str
    title: str
    price: float
    currency: str
    in_stock: bool
    stock: int
    rating: float | None = None
    match_score: float
    reasons: list[str]
    unmet_requirements: list[str]
    price_checked_at: str


class ShopOut(BaseModel):
    interpreted_needs: Needs
    recommendations: list[Recommendation]
    comparison: list[dict[str, Any]]
    delivery: dict[str, Any]
    cart_prepared: bool
    checkout_status: str
    message: str


def parse_needs(query: str, budget: float | None, category: str | None, must: list[str]) -> Needs:
    b = budget
    m = re.search(r"(under|below|less than|max|up to|budget of)\s*\$?\s*([\d,.]+k?)", query, re.I)
    if b is None and m:
        b = to_float(m.group(2))
    musts = list(must)
    for mm in re.finditer(r"(?:with|must have|needs?|that has)\s+([a-z0-9\- ]{3,30}?)(?:,|\.|$| and )", query, re.I):
        musts.append(mm.group(1).strip())
    budget_words = {"under", "below", "less", "than", "max", "budget"}
    kws = [t for t in tokenize(query) if t not in budget_words and not t.isdigit()]
    return Needs(keywords=kws[:12], budget_max=b, category=category, must_have=list(dict.fromkeys(x.lower() for x in musts if x)))


@register
class ShoppingAssistantAgent(BaseAgent):
    spec = AgentSpec(
        key="shopping_assistant",
        name="AI Shopping Assistant",
        department="ecommerce",
        version="1.2.0",
        description="Finds and compares products from the verified catalog against the shopper's needs and budget, with live price and stock, and prepares a draft cart.",
        use_cases=["Guided product discovery", "Spec comparison", "Cart preparation"],
        input_model=ShopIn,
        output_model=ShopOut,
        allowed_tools=["commerce.search_products", "commerce.get_product", "commerce.price_and_stock", "commerce.delivery_policy", "commerce.create_cart"],
        permission_scopes=["commerce:read", "commerce:write"],
        policies=["authoritative_prices_only", "no_checkout_without_confirmation"],
        timeout_seconds=45,
        token_budget=6000,
        risk_level="low",
        model_tier="fast",
        baseline_minutes_saved=6,
    )

    def run(self, ctx: AgentContext, payload: ShopIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        wrapped = guard_untrusted(result, payload.query, "shopper_query", 2000)
        needs = services.structured(
            task="shopping_needs", schema=Needs,
            system="Extract shopping keywords, maximum budget, category and must-have features from the shopper's request.",
            user=wrapped, heuristic=lambda: parse_needs(payload.query, payload.budget_max, payload.category, payload.must_have), tier="fast",
        )
        if payload.budget_max:
            needs.budget_max = payload.budget_max
        candidates = services.tools.call("commerce.search_products", query=" ".join(needs.keywords) or payload.query, category=needs.category, limit=12).get("items", [])
        if not candidates and needs.category:
            candidates = services.tools.call("commerce.search_products", query=" ".join(needs.keywords), limit=12).get("items", [])

        recs: list[Recommendation] = []
        for p in candidates:
            live = services.tools.call("commerce.price_and_stock", product_id=p["id"])  # authoritative price, never the cached listing
            price = float(live["price"])
            text = " ".join([str(p.get("title", "")), str(p.get("description", "")), " ".join(map(str, p.get("tags", []))), " ".join(f"{k} {v}" for k, v in (p.get("specs") or {}).items())]).lower()
            reasons: list[str] = []
            unmet: list[str] = []
            hits = [k for k in needs.keywords if k in text]
            if hits:
                reasons.append(f"Matches: {', '.join(hits[:5])}")
            for req in needs.must_have:
                if all(t in text for t in tokenize(req)):
                    reasons.append(f"Has {req}")
                else:
                    unmet.append(req)
            if needs.budget_max is not None:
                if price <= needs.budget_max:
                    reasons.append(f"Within budget ({price:.2f} ≤ {needs.budget_max:.2f})")
                else:
                    unmet.append(f"Over budget by {price - needs.budget_max:.2f}")
            if live["in_stock"]:
                reasons.append("In stock")
            else:
                unmet.append("Out of stock")
            met_musts = len(needs.must_have) - len([u for u in unmet if u in needs.must_have])
            score = len(hits) * 2 + met_musts * 3 + (2 if live["in_stock"] else -5) + (2 if needs.budget_max is None or price <= needs.budget_max else -6) + float(p.get("rating") or 0) / 2
            recs.append(Recommendation(product_id=p["id"], title=p["title"], price=price, currency=live.get("currency", "USD"), in_stock=bool(live["in_stock"]), stock=int(live.get("stock") or 0), rating=p.get("rating"), match_score=round(score, 2), reasons=reasons, unmet_requirements=unmet, price_checked_at=live["checked_at"]))
            result.add_evidence(f"commerce:product:{p['id']}", excerpt=f"{p['title']} @ {price:.2f}, stock {live.get('stock')}", source_type="commerce")
        recs.sort(key=lambda r: -r.match_score)
        top = recs[:3]

        spec_keys: list[str] = []
        details: dict[str, dict[str, Any]] = {}
        for r in top:
            prod = services.tools.call("commerce.get_product", product_id=r.product_id)
            details[r.product_id] = prod.get("specs") or {}
            spec_keys.extend(k for k in details[r.product_id] if k not in spec_keys)
        comparison = [{"attribute": k, **{r.title: details[r.product_id].get(k, "—") for r in top}} for k in spec_keys[:12]]
        delivery = services.tools.call("commerce.delivery_policy")
        result.add_evidence("commerce:policy:delivery", excerpt=str({k: delivery.get(k) for k in ("standard_days", "free_shipping_threshold", "returns_days")}), source_type="commerce")

        cart_prepared = False
        if payload.add_to_cart:
            valid = []
            for line in payload.add_to_cart:
                try:
                    ps = services.tools.call("commerce.price_and_stock", product_id=line.product_id)
                    if ps["in_stock"] and int(ps.get("stock") or 0) >= line.quantity:
                        valid.append(line.model_dump())
                    else:
                        result.warnings.append(f"{line.product_id}: insufficient stock for quantity {line.quantity}")
                except NotFound:
                    result.warnings.append(f"Product {line.product_id} not found")
            if valid:
                result.proposed_actions.append(ProposedAction(action_type="commerce.prepare_cart", tool_key="commerce.create_cart", payload={"items": valid, "customer_id": payload.customer_id}, reason="Prepare draft cart (no purchase)", risk_level="low", estimated_minutes_saved=2))
                cart_prepared = True
        checkout = "not_requested"
        if payload.confirm_checkout:
            checkout = "requires_customer_confirmation_in_storefront"
            result.warnings.append("Checkout is never executed by the assistant; the customer must confirm payment in the storefront")
            result.missing_information.append("Explicit customer confirmation at checkout (storefront)")
        if not recs:
            result.missing_information.append("No catalog products match; ask the shopper to broaden their criteria")
            msg = "I couldn't find products that match. Could you tell me more about what you need or adjust your budget?"
        else:
            best = top[0]
            msg = f"Top pick: {best.title} at {best.currency} {best.price:.2f} ({'in stock' if best.in_stock else 'out of stock'}). " + "; ".join(best.reasons[:3])
            if best.unmet_requirements:
                msg += f". Note: {', '.join(best.unmet_requirements)}"
            if delivery.get("free_shipping_threshold") is not None:
                msg += f". Free standard shipping over {delivery['free_shipping_threshold']}."
        result.data = ShopOut(interpreted_needs=needs, recommendations=top, comparison=comparison, delivery=delivery, cart_prepared=cart_prepared, checkout_status=checkout, message=msg).model_dump()
        result.summary = f"{len(recs)} candidate(s); recommended {len(top)}" + (" · draft cart prepared" if cart_prepared else "")
        result.confidence = 0.85 if top and not top[0].unmet_requirements else 0.6 if top else 0.2
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved
        return result
