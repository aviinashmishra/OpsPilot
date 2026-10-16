"""Agent 18 - Expense Audit.

Checks expense claims against the configurable company policy: missing
receipts, category limits, prohibited categories, duplicate claims, amount
inconsistencies, weekend/out-of-period items. Every flag names its evidence;
nothing is phrased as an accusation and no employee attributes other than
the claim data are used. Flagged claims are routed to authorised reviewers.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentResult, AgentSpec, BaseAgent, ProposedAction
from app.agents.common import money, parse_dt, strip_protected
from app.agents.registry import register
from app.agents.services import AgentServices


class ExpenseIn(AgentInput):
    claim_ids: list[str] | None = None
    status: str | None = "submitted"
    max_claims: int = Field(default=500, ge=1, le=5000)


class Flag(BaseModel):
    code: str
    severity: str
    detail: str
    policy_ref: str
    evidence: list[str]


class ClaimReview(BaseModel):
    claim_id: str
    employee_id: str | None
    category: str | None
    amount: float
    currency: str
    flags: list[Flag]
    outcome: str  # pass|review|reject_recommended


class ExpenseOut(BaseModel):
    reviewed: int
    passed: int
    flagged: int
    claims: list[ClaimReview]
    policy_summary: dict[str, Any]


@register
class ExpenseAuditAgent(BaseAgent):
    spec = AgentSpec(
        key="expense_audit",
        name="Expense Audit Agent",
        department="finance_admin",
        version="1.0.2",
        description="Audits expense claims against configurable policy with evidence-backed, non-accusatory flags and routes exceptions to authorised reviewers.",
        use_cases=["Pre-reimbursement audit", "Duplicate claim detection", "Policy exception routing"],
        input_model=ExpenseIn,
        output_model=ExpenseOut,
        allowed_tools=["accounting.list_expense_claims", "accounting.get_expense_claim", "accounting.expense_policy", "accounting.flag_expense", "platform.create_task"],
        permission_scopes=["accounting:read", "accounting:write", "tasks:write"],
        policies=["evidence_per_flag", "no_accusations", "no_discriminatory_inference", "route_to_reviewers"],
        timeout_seconds=90,
        token_budget=2000,
        risk_level="medium",
        baseline_minutes_saved=20,
    )

    def run(self, ctx: AgentContext, payload: ExpenseIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        policy = services.tools.call("accounting.expense_policy")
        result.add_evidence("policy:expense", excerpt=f"receipt>{policy.get('receipt_required_above')}, limits {policy.get('category_limits')}", source_type="policy")
        if payload.claim_ids:
            claims = []
            for cid in payload.claim_ids:
                try:
                    claims.append(services.tools.call("accounting.get_expense_claim", claim_id=cid))
                except Exception:  # noqa: BLE001
                    result.warnings.append(f"Claim {cid} not found")
        else:
            claims = services.tools.call("accounting.list_expense_claims", status=payload.status, limit=payload.max_claims).get("items", [])
        history = services.tools.call("accounting.list_expense_claims", limit=5000).get("items", [])
        reviews: list[ClaimReview] = []
        removed_all: set[str] = set()
        limits = policy.get("category_limits", {})
        prohibited = {p.lower() for p in policy.get("prohibited_categories", [])}
        window = int(policy.get("duplicate_window_days", 7))
        for raw in claims:
            c, removed = strip_protected(raw)
            removed_all.update(removed)
            cid = str(c["id"])
            ref = f"accounting:expense_claim:{cid}"
            amt = money(c.get("amount", 0))
            cat = str(c.get("category") or "other").lower()
            flags: list[Flag] = []
            if not c.get("receipt_url") and amt > money(policy.get("receipt_required_above", 25)):
                flags.append(Flag(code="missing_receipt", severity="medium", detail=f"Amount {amt} exceeds the receipt threshold {policy.get('receipt_required_above')} and no receipt is attached", policy_ref="policy:expense#receipts", evidence=[ref]))
            if cat in limits and amt > money(limits[cat]):
                flags.append(Flag(code="over_category_limit", severity="high", detail=f"{cat} claim {amt} exceeds the {limits[cat]} limit", policy_ref=f"policy:expense#limits.{cat}", evidence=[ref]))
            if cat in prohibited:
                flags.append(Flag(code="prohibited_category", severity="high", detail=f"Category '{cat}' is not reimbursable under policy", policy_ref="policy:expense#prohibited", evidence=[ref]))
            items = c.get("line_items") or []
            if items:
                s = sum((money(i.get("amount", 0)) for i in items), money(0))
                if abs(s - amt) > money(0.01):
                    flags.append(Flag(code="amount_inconsistent", severity="high", detail=f"Line items sum to {s} but claim amount is {amt}", policy_ref="policy:expense#accuracy", evidence=[ref]))
            if c.get("receipt_amount") is not None and abs(money(c["receipt_amount"]) - amt) > money(0.01):
                flags.append(Flag(code="receipt_amount_mismatch", severity="high", detail=f"Receipt shows {money(c['receipt_amount'])}, claim is {amt}", policy_ref="policy:expense#accuracy", evidence=[ref]))
            d = parse_dt(c.get("expense_date"))
            sub = parse_dt(c.get("submitted_at"))
            if d and sub and (sub - d).days > int(policy.get("max_days_to_submit", 60)):
                flags.append(Flag(code="late_submission", severity="low", detail=f"Submitted {(sub - d).days} days after the expense date (limit {policy.get('max_days_to_submit', 60)})", policy_ref="policy:expense#timing", evidence=[ref]))
            if d and d > ctx.now:
                flags.append(Flag(code="future_dated", severity="high", detail=f"Expense date {d.date()} is in the future", policy_ref="policy:expense#accuracy", evidence=[ref]))
            for h in history:
                if h.get("id") == cid or h.get("employee_id") != c.get("employee_id"):
                    continue
                hd = parse_dt(h.get("expense_date"))
                if money(h.get("amount", 0)) == amt and str(h.get("merchant", "")).lower() == str(c.get("merchant", "")).lower() and d and hd and abs((d - hd).days) <= window:
                    flags.append(Flag(code="possible_duplicate", severity="high", detail=f"Same merchant and amount as claim {h['id']} dated {hd.date()} (within {window} days)", policy_ref="policy:expense#duplicates", evidence=[ref, f"accounting:expense_claim:{h['id']}"]))
                    break
            result.add_evidence(ref, excerpt=f"{cat} {amt} {c.get('merchant', '')}", source_type="accounting")
            high = [f for f in flags if f.severity == "high"]
            outcome = "pass" if not flags else ("reject_recommended" if any(f.code in {"prohibited_category", "future_dated"} for f in high) else "review")
            reviews.append(ClaimReview(claim_id=cid, employee_id=c.get("employee_id"), category=cat, amount=float(amt), currency=c.get("currency", "USD"), flags=flags, outcome=outcome))
            if flags:
                result.proposed_actions.append(ProposedAction(action_type="accounting.flag_expense", tool_key="accounting.flag_expense", payload={"claim_id": cid, "flags": [f.model_dump() for f in flags]}, reason=f"{len(flags)} policy flag(s) — reviewer attention", risk_level="medium", evidence_refs=[ref], estimated_minutes_saved=4))
        flagged = [r for r in reviews if r.flags]
        if flagged:
            result.proposed_actions.append(ProposedAction(action_type="platform.create_task", tool_key="platform.create_task", payload={"title": f"Expense review: {len(flagged)} flagged claim(s)", "description": "\n".join(f"- {r.claim_id} ({r.outcome}): " + "; ".join(f.detail for f in r.flags) for r in flagged[:30]), "priority": "medium", "labels": ["expenses", "review"], "evidence_refs": [f"accounting:expense_claim:{r.claim_id}" for r in flagged[:20]]}, reason="Route to authorised expense reviewers", risk_level="low"))
        if removed_all:
            result.warnings.append(f"Ignored employee attributes not relevant to policy: {', '.join(sorted(removed_all))}")
        result.data = ExpenseOut(reviewed=len(reviews), passed=len(reviews) - len(flagged), flagged=len(flagged), claims=reviews, policy_summary={k: policy.get(k) for k in ("receipt_required_above", "category_limits", "duplicate_window_days", "prohibited_categories")}).model_dump()
        result.summary = f"{len(reviews)} claim(s) audited: {len(flagged)} flagged for review"
        result.confidence = 0.95
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved if reviews else 0
        return result
