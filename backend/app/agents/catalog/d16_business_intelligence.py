"""Agent 16 - Business Intelligence.

Retrieves authorised metrics, computes KPIs and period-over-period comparisons
in code, explains changes with evidence, labels correlations explicitly as
non-causal, and emits data-quality warnings with recommendations.
"""

from __future__ import annotations

import statistics
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentResult, AgentSpec, BaseAgent
from app.agents.common import linear_slope, pearson
from app.agents.registry import register
from app.agents.services import AgentServices
from app.core.errors import NotFound


class BIIn(AgentInput):
    metrics: list[str] | None = None
    period_days: int = Field(default=14, ge=7, le=90)
    question: str | None = None


class MetricReport(BaseModel):
    key: str
    label: str | None
    unit: str | None
    current_total: float
    previous_total: float
    change_pct: float | None
    trend_slope_per_day: float
    anomalies: list[dict[str, Any]]
    data_quality: list[str]
    evidence_ref: str


class Correlation(BaseModel):
    a: str
    b: str
    r: float
    note: str


class BIOut(BaseModel):
    period_days: int
    metrics: list[MetricReport]
    correlations: list[Correlation]
    narrative: str
    recommendations: list[str]
    data_quality_warnings: list[str]
    method: str


class Narrative(BaseModel):
    narrative: str = Field(max_length=2500)
    recommendations: list[str] = Field(default_factory=list)


@register
class BusinessIntelligenceAgent(BaseAgent):
    spec = AgentSpec(
        key="business_intelligence",
        name="Business Intelligence Agent",
        department="operations",
        version="1.1.0",
        description="Computes KPIs and comparisons deterministically from authorised metrics, explains changes with evidence and clearly separates correlation from causation.",
        use_cases=["Weekly KPI report", "Anomaly explanation", "Executive summaries"],
        input_model=BIIn,
        output_model=BIOut,
        allowed_tools=["metrics.list", "metrics.query"],
        permission_scopes=["metrics:read"],
        policies=["deterministic_kpis", "evidence_backed_explanations", "no_causal_claims_from_correlation", "data_quality_warnings"],
        timeout_seconds=90,
        token_budget=8000,
        risk_level="low",
        baseline_minutes_saved=60,
    )

    def run(self, ctx: AgentContext, payload: BIIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        keys = payload.metrics or [m["key"] for m in services.tools.call("metrics.list").get("items", [])][:8]
        n = payload.period_days
        reports: list[MetricReport] = []
        series: dict[str, list[float]] = {}
        dq_all: list[str] = []
        for key in keys:
            try:
                m = services.tools.call("metrics.query", metric_key=key, days=n * 2)
            except NotFound:
                result.warnings.append(f"Metric '{key}' not found")
                continue
            pts = m.get("points", [])
            vals = [float(p.get("value", 0)) for p in pts if p.get("value") is not None]
            nulls = sum(1 for p in pts if p.get("value") is None)
            dq: list[str] = []
            if len(pts) < n * 2:
                dq.append(f"Only {len(pts)} of {n * 2} expected days available")
            if nulls:
                dq.append(f"{nulls} missing day(s)")
            if m.get("quality", {}).get("source_delayed"):
                dq.append("Source reported delayed data")
            cur, prev = vals[-n:], vals[-2 * n : -n]
            cur_t, prev_t = sum(cur), sum(prev)
            change = round((cur_t - prev_t) / prev_t * 100, 2) if prev_t else None
            anomalies = []
            if len(vals) >= 14:
                mu, sd = statistics.fmean(vals[:-1]), statistics.pstdev(vals[:-1])
                for p, v in zip(pts[-n:], cur, strict=False):
                    if sd and abs(v - mu) > 3 * sd:
                        anomalies.append({"date": p.get("date"), "value": v, "z": round((v - mu) / sd, 2)})
            ref = f"metric:{key}"
            result.add_evidence(ref, excerpt=f"{n}d total {cur_t:.2f} vs prior {prev_t:.2f}", source_type="metrics")
            reports.append(MetricReport(key=key, label=m.get("label"), unit=m.get("unit"), current_total=round(cur_t, 2), previous_total=round(prev_t, 2), change_pct=change, trend_slope_per_day=round(linear_slope(cur), 4), anomalies=anomalies, data_quality=dq, evidence_ref=ref))
            series[key] = vals
            dq_all.extend(f"{key}: {d}" for d in dq)
        correlations: list[Correlation] = []
        ks = list(series)
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                r = pearson(series[ks[i]], series[ks[j]])
                if r is not None and abs(r) >= 0.7:
                    correlations.append(Correlation(a=ks[i], b=ks[j], r=round(r, 3), note="Correlation only — does not establish causation; confounders (seasonality, campaigns) not controlled"))
        facts = "\n".join(f"[{r.evidence_ref}] {r.label or r.key}: {r.current_total} vs {r.previous_total} ({'n/a' if r.change_pct is None else f'{r.change_pct:+.1f}%'}), slope {r.trend_slope_per_day}/day, anomalies {len(r.anomalies)}, dq {r.data_quality or 'ok'}" for r in reports)

        def heuristic() -> Narrative:
            parts, recs = [], []
            for r in sorted(reports, key=lambda x: -abs(x.change_pct or 0)):
                if r.change_pct is None:
                    parts.append(f"{r.label or r.key}: no prior-period baseline.")
                    continue
                parts.append(f"{r.label or r.key} {'rose' if r.change_pct > 0 else 'fell'} {abs(r.change_pct):.1f}% to {r.current_total:g}{(' ' + r.unit) if r.unit else ''} over the last {n} days [{r.evidence_ref}].")
                if abs(r.change_pct) >= 15:
                    recs.append(f"Investigate the {abs(r.change_pct):.0f}% {'increase' if r.change_pct > 0 else 'decrease'} in {r.label or r.key}; check for the drivers listed in evidence before acting.")
            for c in correlations:
                parts.append(f"{c.a} and {c.b} move together (r={c.r}); this is a correlation, not evidence of causation.")
            if dq_all:
                recs.append("Resolve data-quality gaps before using these figures for decisions.")
            return Narrative(narrative=" ".join(parts) or "No metrics available.", recommendations=recs[:5])

        narrative = services.structured(
            task="bi_narrative", schema=Narrative,
            system="Write a short executive narrative using ONLY the computed figures provided (cite the [metric:...] refs). Never state that one metric caused another; describe correlations as correlations. Give up to 5 actionable recommendations.",
            user=f"Period: {n} days vs prior {n} days\n{facts}\nCorrelations: {[c.model_dump() for c in correlations]}\nQuestion: {payload.question or 'general review'}",
            heuristic=heuristic,
        )
        if any(w in narrative.narrative.lower() for w in ("caused by", "because of", "due to", "drove", "led to")) and correlations:
            result.warnings.append("Narrative contained causal language; replaced with deterministic narrative")
            narrative = heuristic()
        result.data = BIOut(period_days=n, metrics=reports, correlations=correlations, narrative=narrative.narrative, recommendations=narrative.recommendations, data_quality_warnings=dq_all, method="Sum over period vs prior period; OLS slope; z-score anomalies (>3σ vs history); Pearson r on daily values (|r|≥0.7 reported, non-causal)").model_dump()
        result.summary = f"{len(reports)} metric(s) analysed; {sum(len(r.anomalies) for r in reports)} anomaly(ies); {len(correlations)} correlation(s); {len(dq_all)} data-quality warning(s)"
        result.confidence = 0.8 if not dq_all else 0.6
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved if reports else 0
        return result
