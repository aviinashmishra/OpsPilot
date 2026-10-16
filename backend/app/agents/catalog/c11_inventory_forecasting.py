"""Agent 11 - Inventory Forecasting.

Baseline demand forecasts (moving average with day-of-week seasonality and a
trend check), deterministic safety stock / reorder point / order quantity, an
80% prediction interval, and explicit data-sufficiency flags. Purchase orders
are only proposed, and always need approval (critical-risk tool).
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentResult, AgentSpec, BaseAgent, ProposedAction
from app.agents.common import z_for_service_level
from app.agents.registry import register
from app.agents.services import AgentServices
from app.core.errors import NotFound

MIN_HISTORY_DAYS = 28


class ForecastIn(AgentInput):
    skus: list[str] | None = None
    horizon_days: int = Field(default=30, ge=7, le=180)
    service_level: float = Field(default=0.95, ge=0.8, le=0.99)
    propose_purchase_orders: bool = True


class SkuForecast(BaseModel):
    sku: str
    name: str | None
    on_hand: int
    on_order: int
    history_days: int
    avg_daily_demand: float | None
    demand_std: float | None
    trend_pct_14d: float | None
    seasonality_applied: bool
    forecast_horizon_units: float | None
    interval_80: list[float] | None
    lead_time_days: int | None
    safety_stock: float | None
    reorder_point: float | None
    days_of_cover: float | None
    recommended_order_qty: int
    status: str
    flags: list[str]


class ForecastOut(BaseModel):
    horizon_days: int
    service_level: float
    method: str
    assumptions: list[str]
    skus: list[SkuForecast]
    reorder_count: int


def forecast_sku(inv: dict[str, Any], series: list[float], horizon: int, service_level: float) -> SkuForecast:
    flags: list[str] = []
    sku = inv["sku"]
    on_hand = int(inv.get("on_hand", 0))
    on_order = int(inv.get("on_order", 0))
    lt = inv.get("lead_time_days")
    if len(series) < MIN_HISTORY_DAYS:
        flags.append(f"Insufficient history ({len(series)} days < {MIN_HISTORY_DAYS}); no forecast produced")
        return SkuForecast(sku=sku, name=inv.get("name"), on_hand=on_hand, on_order=on_order, history_days=len(series), avg_daily_demand=None, demand_std=None, trend_pct_14d=None, seasonality_applied=False, forecast_horizon_units=None, interval_80=None, lead_time_days=lt, safety_stock=None, reorder_point=None, days_of_cover=None, recommended_order_qty=0, status="insufficient_data", flags=flags)
    if lt is None:
        flags.append("Supplier lead time unknown; reorder point cannot be computed")
    recent = series[-28:]
    avg = statistics.fmean(recent)
    std = statistics.pstdev(recent) if len(recent) > 1 else 0.0
    prev14, last14 = sum(series[-28:-14]), sum(series[-14:])
    trend = ((last14 - prev14) / prev14 * 100) if prev14 else None
    if trend is not None and abs(trend) >= 30:
        flags.append(f"Demand trend {trend:+.0f}% over last 14 days — baseline may lag")
    seasonal = len(series) >= 56
    if seasonal:
        by_dow: dict[int, list[float]] = defaultdict(list)
        for i, v in enumerate(series[-56:]):
            by_dow[i % 7].append(v)
        overall = statistics.fmean(series[-56:]) or 1.0
        idx = {d: (statistics.fmean(v) / overall if overall else 1.0) for d, v in by_dow.items()}
        start = len(series) % 7
        horizon_units = sum(avg * idx[(start + h) % 7] for h in range(horizon))
    else:
        horizon_units = avg * horizon
    zero_share = sum(1 for v in recent if v == 0) / len(recent)
    if zero_share > 0.5:
        flags.append("Intermittent demand (>50% zero days); interval is unreliable")
    half = 1.2816 * std * math.sqrt(horizon)
    interval = [round(max(0.0, horizon_units - half), 1), round(horizon_units + half, 1)]
    if std > avg and avg > 0:
        flags.append("High demand variability (CV > 1)")
    safety = rop = None
    qty = 0
    if lt is not None:
        z = z_for_service_level(service_level)
        safety = z * std * math.sqrt(lt)
        rop = avg * lt + safety
        position = on_hand + on_order
        if position <= rop:
            raw = rop + horizon_units - position
            moq = int(inv.get("moq", 1) or 1)
            pack = int(inv.get("case_pack", 1) or 1)
            qty = max(moq, math.ceil(raw / pack) * pack) if raw > 0 else 0
    cover = round(on_hand / avg, 1) if avg > 0 else None
    status = "reorder" if qty > 0 else ("stockout_risk" if cover is not None and lt is not None and cover < lt else "ok")
    return SkuForecast(sku=sku, name=inv.get("name"), on_hand=on_hand, on_order=on_order, history_days=len(series), avg_daily_demand=round(avg, 2), demand_std=round(std, 2), trend_pct_14d=round(trend, 1) if trend is not None else None, seasonality_applied=seasonal, forecast_horizon_units=round(horizon_units, 1), interval_80=interval, lead_time_days=lt, safety_stock=round(safety, 1) if safety is not None else None, reorder_point=round(rop, 1) if rop is not None else None, days_of_cover=cover, recommended_order_qty=int(qty), status=status, flags=flags)


@register
class InventoryForecastingAgent(BaseAgent):
    spec = AgentSpec(
        key="inventory_forecasting",
        name="Inventory Forecasting Agent",
        department="ecommerce",
        version="1.0.4",
        description="Forecasts SKU demand with transparent statistics, quantifies uncertainty and computes reorder recommendations; purchase orders always need approval.",
        use_cases=["Weekly replenishment", "Stockout risk review", "Supplier PO preparation"],
        input_model=ForecastIn,
        output_model=ForecastOut,
        allowed_tools=["commerce.list_inventory", "commerce.get_inventory", "commerce.sales_history", "commerce.supplier_lead_time", "commerce.create_purchase_order"],
        permission_scopes=["commerce:read", "procurement:commit"],
        policies=["deterministic_reorder_math", "explicit_uncertainty", "no_po_without_authorization"],
        timeout_seconds=120,
        token_budget=4000,
        risk_level="high",
        baseline_minutes_saved=40,
    )

    def run(self, ctx: AgentContext, payload: ForecastIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        if payload.skus:
            inventory = []
            for s in payload.skus:
                try:
                    inventory.append(services.tools.call("commerce.get_inventory", sku=s))
                except NotFound:
                    result.warnings.append(f"No inventory record for {s}")
        else:
            inventory = services.tools.call("commerce.list_inventory").get("items", [])
        forecasts: list[SkuForecast] = []
        for inv in inventory:
            hist = services.tools.call("commerce.sales_history", sku=inv["sku"], days=120)
            series = [float(x) for x in hist.get("daily_units", [])]
            f = forecast_sku(inv, series, payload.horizon_days, payload.service_level)
            forecasts.append(f)
            result.add_evidence(f"commerce:sales_history:{inv['sku']}", excerpt=f"{len(series)} days, avg {f.avg_daily_demand}", source_type="commerce")
            if f.status == "insufficient_data":
                result.missing_information.append(f"{inv['sku']}: at least {MIN_HISTORY_DAYS} days of sales history")
        by_supplier: dict[str, list[SkuForecast]] = defaultdict(list)
        unit_cost = {i["sku"]: i.get("unit_cost") for i in inventory}
        supplier_of = {i["sku"]: i.get("supplier_id") for i in inventory}
        for f in forecasts:
            if f.recommended_order_qty > 0 and supplier_of.get(f.sku):
                by_supplier[supplier_of[f.sku]].append(f)
        if payload.propose_purchase_orders:
            for sup, items in by_supplier.items():
                lines = [{"sku": f.sku, "quantity": f.recommended_order_qty, "unit_cost": unit_cost.get(f.sku) or 0} for f in items]
                total = round(sum(float(line["unit_cost"]) * line["quantity"] for line in lines), 2)
                result.proposed_actions.append(ProposedAction(action_type="commerce.purchase_order", tool_key="commerce.create_purchase_order", payload={"supplier_id": sup, "lines": lines, "total": total}, reason=f"Replenish {len(lines)} SKU(s) at/below reorder point", risk_level="critical", evidence_refs=[f"commerce:sales_history:{f.sku}" for f in items], estimated_minutes_saved=15))
        reorder = sum(1 for f in forecasts if f.recommended_order_qty > 0)
        result.data = ForecastOut(
            horizon_days=payload.horizon_days, service_level=payload.service_level,
            method="28-day moving average × day-of-week index (when ≥56 days); safety stock = z·σ·√LT; ROP = μ·LT + SS; order = ROP + horizon demand − (on hand + on order), rounded to MOQ/case pack",
            assumptions=["Demand is stationary within the 28-day window", "Lead times are as recorded by the supplier", "Stockouts in history are not corrected for (censored demand)", "Promotions are not modelled"],
            skus=forecasts, reorder_count=reorder,
        ).model_dump()
        result.summary = f"{len(forecasts)} SKU(s) forecast for {payload.horizon_days} days; {reorder} need reorder; {sum(1 for f in forecasts if f.status == 'insufficient_data')} with insufficient data"
        result.confidence = 0.75
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved
        return result
