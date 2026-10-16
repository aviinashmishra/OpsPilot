"""Agent 25 - Finance-Aware Business Analyst.

Combines authorised cost ledgers, revenue, OpsPilot workflow usage and
productivity baselines to compute cost per successful workflow and estimated
value created, strictly separating *estimated labour value* from *realized
savings*, and flags cost anomalies and budget breaches. Read-only: it never
pays, invests or alters records.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentResult, AgentSpec, BaseAgent, ProposedAction
from app.agents.registry import register
from app.agents.services import AgentServices


class FinanceIn(AgentInput):
    months: int = Field(default=3, ge=1, le=24)
    loaded_hourly_cost_usd: float | None = None
    realization_rate: float | None = Field(default=None, ge=0, le=1, description="Finance-verified share of saved time converted into realized savings")


class WorkflowEconomics(BaseModel):
    workflow_key: str
    runs: int
    succeeded: int
    ai_cost_usd: float
    infra_cost_usd: float
    cost_per_successful_run_usd: float | None
    minutes_saved: float
    estimated_labor_value_usd: float
    realized_savings_usd: float
    net_estimated_value_usd: float


class CostAnomaly(BaseModel):
    cost_center: str
    month: str
    amount: float
    baseline_avg: float
    deviation_pct: float
    evidence_ref: str


class BudgetBreach(BaseModel):
    cost_center: str
    budget: float
    actual: float
    utilization: float
    evidence_ref: str


class FinanceOut(BaseModel):
    period_months: int
    assumptions: dict[str, Any]
    totals: dict[str, float]
    workflows: list[WorkflowEconomics]
    cost_anomalies: list[CostAnomaly]
    budget_breaches: list[BudgetBreach]
    revenue_by_month: dict[str, float]
    costs_by_month: dict[str, float]
    notes: list[str]
    actions_taken: str


@register
class FinanceAnalystAgent(BaseAgent):
    spec = AgentSpec(
        key="finance_analyst",
        name="Finance-Aware Business Analyst Agent",
        department="technology_product",
        version="1.0.2",
        description="Computes cost per successful workflow and estimated vs realized value from authorised cost, revenue and usage data; flags cost anomalies and budget breaches. Read-only.",
        use_cases=["Monthly automation ROI", "Budget threshold alerts", "AI spend review"],
        input_model=FinanceIn,
        output_model=FinanceOut,
        allowed_tools=["accounting.cost_ledger", "accounting.revenue", "accounting.budgets", "platform.workflow_usage", "platform.open_incident"],
        permission_scopes=["accounting:read", "tasks:read", "incidents:write"],
        policies=["read_only_finance", "estimated_vs_realized_separation", "deterministic_calculations"],
        timeout_seconds=60,
        token_budget=2000,
        risk_level="low",
        baseline_minutes_saved=120,
    )

    def run(self, ctx: AgentContext, payload: FinanceIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        roi = ctx.tenant_config.get("roi", {}) or {}
        hourly = payload.loaded_hourly_cost_usd or float(roi.get("loaded_hourly_cost_usd", 45.0))
        realization = payload.realization_rate if payload.realization_rate is not None else float(roi.get("realization_rate", 0.0))
        infra_per_run = float(roi.get("infra_cost_per_run_usd", 0.002))
        ledger = services.tools.call("accounting.cost_ledger", months=payload.months).get("items", [])
        revenue = services.tools.call("accounting.revenue", months=payload.months).get("items", [])
        budgets = services.tools.call("accounting.budgets").get("items", [])
        usage = services.tools.call("platform.workflow_usage", days=payload.months * 30).get("items", [])
        result.add_evidence("accounting:cost_ledger", excerpt=f"{len(ledger)} entries", source_type="accounting")
        result.add_evidence("accounting:revenue", excerpt=f"{len(revenue)} entries", source_type="accounting")
        result.add_evidence("platform:workflow_usage", excerpt=f"{len(usage)} workflows", source_type="platform")

        costs_by_month: dict[str, float] = defaultdict(float)
        by_cc_month: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for e in ledger:
            m, cc, amt = str(e.get("month")), str(e.get("cost_center", "unallocated")), float(e.get("amount", 0))
            costs_by_month[m] += amt
            by_cc_month[cc][m] += amt
        revenue_by_month: dict[str, float] = defaultdict(float)
        for r in revenue:
            revenue_by_month[str(r.get("month"))] += float(r.get("amount", 0))
        anomalies: list[CostAnomaly] = []
        for cc, months in by_cc_month.items():
            if len(months) < 3:
                continue
            ordered = sorted(months)
            last, prev = ordered[-1], ordered[:-1]
            base = statistics.fmean(months[m] for m in prev)
            if base > 0 and months[last] > base * 1.3:
                anomalies.append(CostAnomaly(cost_center=cc, month=last, amount=round(months[last], 2), baseline_avg=round(base, 2), deviation_pct=round((months[last] - base) / base * 100, 1), evidence_ref=f"accounting:cost_ledger#{cc}"))
        breaches: list[BudgetBreach] = []
        latest_month = max(costs_by_month) if costs_by_month else None
        for b in budgets:
            cc = str(b.get("cost_center"))
            actual = by_cc_month.get(cc, {}).get(latest_month or "", 0.0)
            budget = float(b.get("monthly_budget", 0))
            if budget and actual / budget >= float(b.get("alert_threshold", 0.9)):
                breaches.append(BudgetBreach(cost_center=cc, budget=budget, actual=round(actual, 2), utilization=round(actual / budget, 4), evidence_ref=f"accounting:budget:{cc}"))
                result.add_evidence(f"accounting:budget:{cc}", excerpt=f"{actual:.2f}/{budget:.2f}", source_type="accounting")
        workflows: list[WorkflowEconomics] = []
        tot = {"runs": 0, "succeeded": 0, "ai_cost_usd": 0.0, "infra_cost_usd": 0.0, "minutes_saved": 0.0}
        for u in usage:
            infra = u["runs"] * infra_per_run
            labor = u["minutes_saved"] / 60 * hourly
            realized = labor * realization
            workflows.append(WorkflowEconomics(workflow_key=u["workflow_key"], runs=u["runs"], succeeded=u["succeeded"], ai_cost_usd=round(u["ai_cost_usd"], 6), infra_cost_usd=round(infra, 4), cost_per_successful_run_usd=round((u["ai_cost_usd"] + infra) / u["succeeded"], 6) if u["succeeded"] else None, minutes_saved=u["minutes_saved"], estimated_labor_value_usd=round(labor, 2), realized_savings_usd=round(realized, 2), net_estimated_value_usd=round(labor - u["ai_cost_usd"] - infra, 2)))
            tot["runs"] += u["runs"]
            tot["succeeded"] += u["succeeded"]
            tot["ai_cost_usd"] += u["ai_cost_usd"]
            tot["infra_cost_usd"] += infra
            tot["minutes_saved"] += u["minutes_saved"]
        labor_total = tot["minutes_saved"] / 60 * hourly
        totals = {**{k: round(v, 4) for k, v in tot.items()}, "cost_per_successful_workflow_usd": round((tot["ai_cost_usd"] + tot["infra_cost_usd"]) / tot["succeeded"], 6) if tot["succeeded"] else 0.0, "estimated_labor_value_usd": round(labor_total, 2), "realized_savings_usd": round(labor_total * realization, 2), "total_costs_usd": round(sum(costs_by_month.values()), 2), "total_revenue_usd": round(sum(revenue_by_month.values()), 2)}
        notes = ["Estimated labour value = minutes saved × loaded hourly cost; it is NOT cash savings.", f"Realized savings apply the finance-verified realization rate ({realization:.0%}); set tenant.settings.roi.realization_rate once verified.", "Minutes saved come from per-agent measured baselines configured in the agent catalog."]
        if realization == 0:
            notes.append("Realization rate is 0% — no realized savings are claimed until finance verifies them.")
        for a in anomalies:
            result.add_evidence(a.evidence_ref, excerpt=f"{a.month} {a.amount} vs avg {a.baseline_avg}", source_type="accounting")
        if anomalies or breaches:
            result.proposed_actions.append(ProposedAction(action_type="platform.open_incident", tool_key="platform.open_incident", payload={"title": f"Finance: {len(anomalies)} cost anomaly(ies), {len(breaches)} budget threshold breach(es)", "severity": "high" if breaches else "medium", "kind": "cost_anomaly", "details": {"anomalies": [a.model_dump() for a in anomalies], "breaches": [b.model_dump() for b in breaches]}}, reason="Budget/cost alert for finance review", risk_level="low", evidence_refs=[a.evidence_ref for a in anomalies] + [b.evidence_ref for b in breaches], estimated_minutes_saved=20))
        result.data = FinanceOut(period_months=payload.months, assumptions={"loaded_hourly_cost_usd": hourly, "realization_rate": realization, "infra_cost_per_run_usd": infra_per_run}, totals=totals, workflows=workflows, cost_anomalies=anomalies, budget_breaches=breaches, revenue_by_month=dict(sorted(revenue_by_month.items())), costs_by_month=dict(sorted(costs_by_month.items())), notes=notes, actions_taken="read-only analysis; no payments, investments or record changes").model_dump()
        result.summary = f"{tot['runs']} workflow run(s): cost/success ${totals['cost_per_successful_workflow_usd']:.4f}, est. labour value ${labor_total:,.0f}, realized ${labor_total * realization:,.0f}; {len(anomalies)} anomaly(ies), {len(breaches)} budget breach(es)"
        result.confidence = 0.9
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved
        return result
