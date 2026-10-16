"""Agent 23 - Product Research.

Clusters authorised customer feedback into recurring themes with supporting
examples, estimates frequency transparently (count / total, with a Wilson
interval), separates evidence from hypotheses, and recommends experiments.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentResult, AgentSpec, BaseAgent, ProposedAction
from app.agents.common import tokenize, wilson_interval
from app.agents.registry import register
from app.agents.services import AgentServices
from app.llm.safety import scan_for_injection

THEME_SEEDS: dict[str, list[str]] = {
    "performance": ["slow", "lag", "loading", "freeze", "crash", "performance", "speed"],
    "pricing": ["price", "pricing", "expensive", "cost", "cheaper", "plan", "subscription"],
    "onboarding": ["setup", "onboarding", "confusing", "learn", "tutorial", "getting started", "documentation"],
    "integrations": ["integration", "integrate", "api", "export", "import", "sync", "webhook", "zapier"],
    "mobile": ["mobile", "ios", "android", "phone", "tablet"],
    "reporting": ["report", "dashboard", "analytics", "chart", "export"],
    "support": ["support", "response", "help", "ticket", "reply"],
    "reliability": ["bug", "error", "broken", "fails", "outage", "down"],
    "ux": ["ui", "ux", "design", "layout", "navigation", "button", "dark mode"],
}


class ResearchIn(AgentInput):
    sources: list[str] | None = None
    since_days: int = Field(default=90, ge=7, le=730)
    min_theme_size: int = Field(default=3, ge=1, le=100)
    max_items: int = Field(default=2000, ge=10, le=20000)


class Theme(BaseModel):
    name: str
    count: int
    share: float
    interval_95: list[float]
    sources: dict[str, int]
    examples: list[dict[str, Any]]
    top_terms: list[str]
    evidence_refs: list[str]


class ResearchOut(BaseModel):
    total_items: int
    analysed_items: int
    themes: list[Theme]
    evidence_summary: list[str]
    hypotheses: list[str]
    recommended_experiments: list[dict[str, Any]]
    method: str
    unclustered: int


class Synthesis(BaseModel):
    hypotheses: list[str] = Field(default_factory=list)
    experiments: list[dict[str, Any]] = Field(default_factory=list)


@register
class ProductResearchAgent(BaseAgent):
    spec = AgentSpec(
        key="product_research",
        name="Product Research Agent",
        department="technology_product",
        version="1.0.2",
        description="Clusters feedback, reviews, tickets and feature requests into evidence-backed themes with transparent frequencies, and separates hypotheses and experiment ideas from evidence.",
        use_cases=["Voice-of-customer synthesis", "Roadmap prioritisation input", "Experiment proposals"],
        input_model=ResearchIn,
        output_model=ResearchOut,
        allowed_tools=["feedback.list", "platform.create_task"],
        permission_scopes=["feedback:read", "tasks:write"],
        policies=["transparent_frequencies", "evidence_vs_hypothesis", "no_fabricated_research"],
        timeout_seconds=120,
        token_budget=10000,
        risk_level="low",
        baseline_minutes_saved=90,
    )

    def run(self, ctx: AgentContext, payload: ResearchIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        items: list[dict[str, Any]] = []
        for src in payload.sources or [None]:  # type: ignore[list-item]
            items += services.tools.call("feedback.list", source=src, since_days=payload.since_days, limit=payload.max_items).get("items", [])
        seen: set[str] = set()
        items = [i for i in items if not (i["id"] in seen or seen.add(i["id"]))][: payload.max_items]  # type: ignore[func-returns-value]
        injected = 0
        clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
        unclustered = 0
        for it in items:
            text = str(it.get("text") or "")
            if scan_for_injection(text).detected:
                injected += 1
            toks = set(tokenize(text))
            low = text.lower()
            matched = [theme for theme, seeds in THEME_SEEDS.items() if any(s in low for s in seeds)]
            if not matched:
                unclustered += 1
                continue
            for theme in matched:
                clusters[theme].append({**it, "_toks": toks})
        total = len(items)
        themes: list[Theme] = []
        for name, members in clusters.items():
            if len(members) < payload.min_theme_size:
                continue
            lo, hi = wilson_interval(len(members), total)
            src_counts = Counter(str(m.get("source")) for m in members)
            terms = Counter(t for m in members for t in m["_toks"])
            examples = sorted(members, key=lambda m: -(m.get("rating") is not None and m.get("rating", 5) <= 2) - len(m["_toks"]) / 100)[:3]
            refs = [f"feedback:{m['id']}" for m in members[:25]]
            for m in examples:
                result.add_evidence(f"feedback:{m['id']}", excerpt=str(m.get("text"))[:160], source_type=str(m.get("source")))
            themes.append(Theme(name=name, count=len(members), share=round(len(members) / total, 4) if total else 0, interval_95=[round(lo, 4), round(hi, 4)], sources=dict(src_counts), examples=[{"id": m["id"], "source": m.get("source"), "text": str(m.get("text"))[:240], "rating": m.get("rating")} for m in examples], top_terms=[t for t, _ in terms.most_common(6)], evidence_refs=refs))
        themes.sort(key=lambda t: -t.count)
        evidence_summary = [f"{t.name}: {t.count}/{total} items ({t.share:.0%}, 95% CI {t.interval_95[0]:.0%}–{t.interval_95[1]:.0%}) across {', '.join(f'{k} {v}' for k, v in t.sources.items())}" for t in themes]
        theme_block = "\n".join(f"- {s}; examples: " + " | ".join(e['text'][:120] for e in t.examples) for s, t in zip(evidence_summary, themes, strict=True))

        def heuristic() -> Synthesis:
            hyps, exps = [], []
            for t in themes[:4]:
                hyps.append(f"Hypothesis (untested): addressing '{t.name}' would reduce related feedback volume; evidence shows frequency only, not impact on retention or revenue.")
                exps.append({"theme": t.name, "experiment": f"Interview 8–10 customers from the {t.name} cluster and run a prototype test", "metric": f"Share of new feedback mentioning {t.name} (baseline {t.share:.0%})", "duration_weeks": 4})
            return Synthesis(hypotheses=hyps, experiments=exps)

        synth = services.structured(task="research_synthesis", schema=Synthesis, system="Given evidence-backed feedback themes, propose hypotheses explicitly labelled as hypotheses (never as findings) and experiments with a measurable metric. Do not invent statistics, user counts or quotes.", user=theme_block or "(no themes)", heuristic=heuristic)
        import re

        allowed_numbers = set(re.findall(r"\d+", theme_block))
        for h in synth.hypotheses:
            extra = [n for n in re.findall(r"\d+", h) if n not in allowed_numbers]
            if extra:
                result.warnings.append("Discarded a hypothesis containing unsupported figures")
        synth.hypotheses = [h for h in synth.hypotheses if not [n for n in re.findall(r"\d+", h) if n not in allowed_numbers]]
        if themes:
            result.proposed_actions.append(ProposedAction(action_type="platform.create_task", tool_key="platform.create_task", payload={"title": f"Product research digest: top theme '{themes[0].name}' ({themes[0].count}/{total})", "description": "\n".join(evidence_summary) + "\n\nHypotheses:\n- " + "\n- ".join(synth.hypotheses[:5]), "priority": "medium", "labels": ["research"], "evidence_refs": themes[0].evidence_refs[:10]}, reason="Share synthesis with product team", risk_level="low", evidence_refs=themes[0].evidence_refs[:5], estimated_minutes_saved=30))
        if injected:
            result.warnings.append(f"{injected} feedback item(s) contained instruction-like text and were treated as data only")
        result.data = ResearchOut(total_items=total, analysed_items=total - unclustered, themes=themes, evidence_summary=evidence_summary, hypotheses=synth.hypotheses, recommended_experiments=synth.experiments, method="Keyword-seeded clustering (items may belong to several themes); share = count/total; 95% Wilson interval", unclustered=unclustered).model_dump()
        result.summary = f"{total} item(s) → {len(themes)} theme(s); top: " + ", ".join(f"{t.name} ({t.share:.0%})" for t in themes[:3])
        result.confidence = 0.75 if total >= 30 else 0.5
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved if total else 0
        return result
