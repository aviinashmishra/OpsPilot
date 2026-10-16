"""Agent 1 - Lead Qualification.

Normalises inbound leads, detects duplicates, scores them with transparent and
configurable criteria (never protected characteristics), lists missing
information with follow-up questions, and routes qualified leads to a sales team.
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
    BaseAgent,
    ProposedAction,
)
from app.agents.common import guard_untrusted, stable_id, strip_protected, to_float
from app.agents.registry import register
from app.agents.services import AgentServices

DEFAULT_CRITERIA = {
    "qualify_threshold": 60,
    "weights": {"budget": 25, "authority": 20, "timeline": 20, "company_size": 15, "need": 15, "industry_fit": 5},
    "min_budget": 10000,
    "target_industries": ["retail", "ecommerce", "logistics", "saas", "manufacturing", "healthcare", "finance"],
    "decision_titles": ["ceo", "cto", "cfo", "coo", "founder", "owner", "president", "vp", "vice president", "head", "director", "chief"],
    "min_company_size": 20,
}

FOLLOW_UPS = {
    "email": "What is the best email address to reach you?",
    "company": "Which company are you with?",
    "title": "What is your role in the buying decision?",
    "budget": "Do you have a budget range allocated for this initiative?",
    "timeline": "When are you hoping to have a solution in place?",
    "company_size": "Roughly how many employees does your company have?",
    "need": "What problem are you hoping to solve?",
}


class LeadIn(AgentInput):
    lead: dict[str, Any] = Field(description="Raw lead from a form, webhook, CRM or email parser")
    source: str | None = Field(default=None, description="Channel the lead arrived from")


class ScoreComponent(BaseModel):
    criterion: str
    points: float
    max_points: float
    reason: str
    evidence: str | None = None


class LeadOut(BaseModel):
    lead_id: str
    normalized_lead: dict[str, Any]
    score: float
    score_breakdown: list[ScoreComponent]
    qualified: bool
    tier: str
    assigned_team: str | None = None
    routing_reason: str | None = None
    duplicate_of: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    protected_attributes_ignored: list[str] = Field(default_factory=list)
    extracted_need: str | None = None


class NeedExtraction(BaseModel):
    need_summary: str | None = None
    mentioned_budget: float | None = None
    mentioned_timeline_months: float | None = None
    use_case: str | None = None


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


def normalize_lead(raw: dict[str, Any]) -> dict[str, Any]:
    lead = {k.strip().lower().replace(" ", "_"): (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
    name = lead.get("name") or " ".join(filter(None, [lead.get("first_name"), lead.get("last_name")]))
    if name:
        parts = str(name).split()
        lead["name"] = " ".join(p.capitalize() if p.islower() or p.isupper() else p for p in parts)
        lead.setdefault("first_name", parts[0].capitalize())
        if len(parts) > 1:
            lead.setdefault("last_name", " ".join(parts[1:]).capitalize())
    if lead.get("email"):
        lead["email"] = str(lead["email"]).lower()
        if not _EMAIL.match(lead["email"]):
            lead["email_invalid"] = True
    if lead.get("phone"):
        digits = re.sub(r"[^\d+]", "", str(lead["phone"]))
        lead["phone"] = digits
    if lead.get("company"):
        lead["company"] = re.sub(r"\s+", " ", str(lead["company"])).strip()
    for k in ("budget", "company_size", "employees"):
        if lead.get(k) not in (None, ""):
            lead[k] = to_float(lead[k])
    if lead.get("employees") and not lead.get("company_size"):
        lead["company_size"] = lead["employees"]
    if lead.get("industry"):
        lead["industry"] = str(lead["industry"]).lower()
    return {k: v for k, v in lead.items() if v not in (None, "")}


def _timeline_months(text: str | None) -> float | None:
    if not text:
        return None
    t = str(text).lower()
    if any(w in t for w in ("immediately", "asap", "this month", "urgent", "right away")):
        return 0.5
    if "this quarter" in t or "next month" in t:
        return 2
    if "next quarter" in t:
        return 4
    if "this year" in t:
        return 6
    if "next year" in t:
        return 12
    m = re.search(r"(\d+)\s*(week|month|year)", t)
    if m:
        n = float(m.group(1))
        return n / 4 if m.group(2) == "week" else n * 12 if m.group(2) == "year" else n
    return None


def _heuristic_need(lead: dict[str, Any]) -> NeedExtraction:
    msg = str(lead.get("message") or lead.get("notes") or "")
    budget = None
    m = re.search(r"\$\s?([\d,.]+\s?[km]?)", msg, re.I) or re.search(r"budget[^\d$]{0,20}([\d,.]+\s?[km]?)", msg, re.I)
    if m:
        budget = to_float(m.group(1))
    timeline = _timeline_months(msg)
    need = msg.split(".")[0][:200] if msg else None
    return NeedExtraction(need_summary=need, mentioned_budget=budget, mentioned_timeline_months=timeline, use_case=None)


def score_lead(lead: dict[str, Any], need: NeedExtraction, criteria: dict[str, Any]) -> list[ScoreComponent]:
    w = {**DEFAULT_CRITERIA["weights"], **(criteria.get("weights") or {})}
    out: list[ScoreComponent] = []
    budget = lead.get("budget") or need.mentioned_budget
    min_budget = float(criteria.get("min_budget", DEFAULT_CRITERIA["min_budget"]))
    if budget is None:
        out.append(ScoreComponent(criterion="budget", points=0, max_points=w["budget"], reason="Budget not provided"))
    else:
        pts = w["budget"] if budget >= min_budget else round(w["budget"] * budget / min_budget, 1)
        out.append(ScoreComponent(criterion="budget", points=pts, max_points=w["budget"], reason=f"Budget {budget:,.0f} vs minimum {min_budget:,.0f}", evidence="lead.budget" if lead.get("budget") else "lead.message"))
    title = str(lead.get("title") or lead.get("job_title") or "").lower()
    titles = criteria.get("decision_titles", DEFAULT_CRITERIA["decision_titles"])
    if not title:
        out.append(ScoreComponent(criterion="authority", points=0, max_points=w["authority"], reason="Role not provided"))
    elif any(re.search(r"\b" + re.escape(t) + r"\b", title) for t in titles):
        out.append(ScoreComponent(criterion="authority", points=w["authority"], max_points=w["authority"], reason=f"Decision-making role: {title}", evidence="lead.title"))
    elif "manager" in title or "lead" in title:
        out.append(ScoreComponent(criterion="authority", points=round(w["authority"] * 0.5, 1), max_points=w["authority"], reason=f"Influencer role: {title}", evidence="lead.title"))
    else:
        out.append(ScoreComponent(criterion="authority", points=round(w["authority"] * 0.2, 1), max_points=w["authority"], reason=f"Role '{title}' is not a typical decision maker", evidence="lead.title"))
    months = _timeline_months(lead.get("timeline")) if lead.get("timeline") else need.mentioned_timeline_months
    if months is None:
        out.append(ScoreComponent(criterion="timeline", points=0, max_points=w["timeline"], reason="Timeline not provided"))
    else:
        pts = w["timeline"] if months <= 3 else round(w["timeline"] * 0.5, 1) if months <= 6 else round(w["timeline"] * 0.2, 1)
        out.append(ScoreComponent(criterion="timeline", points=pts, max_points=w["timeline"], reason=f"Buying timeline ≈ {months:g} month(s)", evidence="lead.timeline" if lead.get("timeline") else "lead.message"))
    size = lead.get("company_size")
    min_size = float(criteria.get("min_company_size", DEFAULT_CRITERIA["min_company_size"]))
    if size is None:
        out.append(ScoreComponent(criterion="company_size", points=0, max_points=w["company_size"], reason="Company size not provided"))
    else:
        pts = w["company_size"] if size >= min_size * 5 else round(w["company_size"] * 0.6, 1) if size >= min_size else round(w["company_size"] * 0.2, 1)
        out.append(ScoreComponent(criterion="company_size", points=pts, max_points=w["company_size"], reason=f"{size:,.0f} employees", evidence="lead.company_size"))
    if need.need_summary and len(need.need_summary) > 15:
        out.append(ScoreComponent(criterion="need", points=w["need"], max_points=w["need"], reason="Clear stated need", evidence="lead.message"))
    else:
        out.append(ScoreComponent(criterion="need", points=0, max_points=w["need"], reason="No stated need"))
    industry = str(lead.get("industry") or "")
    targets = criteria.get("target_industries", DEFAULT_CRITERIA["target_industries"])
    out.append(ScoreComponent(criterion="industry_fit", points=w["industry_fit"] if industry in targets else 0, max_points=w["industry_fit"], reason=f"Industry '{industry or 'unknown'}' {'in' if industry in targets else 'not in'} target list", evidence="lead.industry" if industry else None))
    return out


@register
class LeadQualificationAgent(BaseAgent):
    spec = AgentSpec(
        key="lead_qualification",
        name="Lead Qualification Agent",
        department="sales_revenue",
        version="1.2.0",
        description="Normalises inbound leads, detects duplicates, scores them with transparent configurable criteria and routes qualified leads to the right sales team.",
        use_cases=["Score web form leads", "Deduplicate CRM inbound", "Route enterprise leads", "Generate discovery questions"],
        input_model=LeadIn,
        output_model=LeadOut,
        allowed_tools=["crm.find_lead", "crm.get_sales_teams", "crm.upsert_lead", "crm.update_lead", "crm.log_activity"],
        permission_scopes=["crm:read", "crm:write"],
        policies=["no_protected_characteristics", "no_invented_lead_data", "transparent_scoring"],
        approval_rules=[],
        timeout_seconds=60,
        token_budget=6000,
        risk_level="low",
        model_tier="fast",
        baseline_minutes_saved=8,
    )

    def run(self, ctx: AgentContext, payload: LeadIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        criteria = {**DEFAULT_CRITERIA, **(ctx.agent_config.get("criteria") or {})}
        cleaned, removed = strip_protected(payload.lead)
        if removed:
            result.warnings.append(f"Ignored protected attributes (never used in scoring): {', '.join(sorted(removed))}")
        lead = normalize_lead(cleaned)
        if lead.get("email_invalid"):
            result.warnings.append(f"Email '{lead['email']}' is not a valid address")
        result.add_evidence("input:lead", excerpt=", ".join(f"{k}={v}" for k, v in list(lead.items())[:8]), source_type="input")

        message = str(lead.get("message") or "")
        need = _heuristic_need(lead)
        if message:
            wrapped = guard_untrusted(result, message, "lead_message", 4000)
            need = services.structured(
                task="lead_need_extraction",
                schema=NeedExtraction,
                system="You extract the buyer's stated need, budget and timeline from an inbound sales lead message. Only use what the message states.",
                user=wrapped,
                heuristic=lambda: _heuristic_need(lead),
                tier="fast",
            )

        # Duplicate detection through the CRM (authoritative system of record)
        dup = services.tools.call("crm.find_lead", email=lead.get("email"), phone=lead.get("phone"), company=None if lead.get("email") else lead.get("company"))
        duplicate_of = dup["matches"][0]["id"] if dup.get("matches") else None
        if duplicate_of:
            result.add_evidence(f"crm:lead:{duplicate_of}", excerpt="Existing CRM lead with the same email/phone", source_type="crm")

        breakdown = score_lead(lead, need, criteria)
        score = round(sum(c.points for c in breakdown), 1)
        threshold = float(criteria.get("qualify_threshold", 60))
        qualified = score >= threshold and not lead.get("email_invalid")
        tier = "A" if score >= threshold + 20 else "B" if score >= threshold else "C" if score >= threshold - 20 else "D"

        missing = [c.criterion for c in breakdown if c.points == 0 and c.criterion in FOLLOW_UPS]
        for f in ("email", "company"):
            if not lead.get(f):
                missing.insert(0, f)
        questions = [FOLLOW_UPS[m] for m in dict.fromkeys(missing) if m in FOLLOW_UPS]
        result.missing_information = list(dict.fromkeys(missing))

        teams = services.tools.call("crm.get_sales_teams").get("items", [])
        assigned, reason = self._route(lead, score, teams)

        lead_id = duplicate_of or stable_id("L", lead.get("email") or lead.get("phone") or f"{lead.get('name')}|{lead.get('company')}")
        status = "qualified" if qualified else ("nurture" if score >= threshold - 30 else "disqualified")
        crm_fields = {
            **{k: v for k, v in lead.items() if k not in {"email_invalid"}},
            "status": status,
            "score": score,
            "tier": tier,
            "assigned_team": assigned,
            "score_breakdown": [c.model_dump() for c in breakdown],
            "source": payload.source or lead.get("source"),
        }
        if duplicate_of:
            result.proposed_actions.append(ProposedAction(action_type="crm.update_lead", tool_key="crm.update_lead", payload={"lead_id": duplicate_of, "fields": crm_fields}, reason="Merge new submission into existing lead (duplicate)", risk_level="low", evidence_refs=[f"crm:lead:{duplicate_of}"], estimated_minutes_saved=3))
        else:
            result.proposed_actions.append(ProposedAction(action_type="crm.create_lead", tool_key="crm.upsert_lead", payload={"lead": {"id": lead_id, **crm_fields}}, reason=f"Create {status} lead (score {score})", risk_level="low", evidence_refs=["input:lead"], estimated_minutes_saved=5))
        result.proposed_actions.append(ProposedAction(action_type="crm.log_activity", tool_key="crm.log_activity", payload={"lead_id": lead_id, "activity_type": "qualification", "note": f"Scored {score}/100 ({tier}); routed to {assigned or 'unassigned'}. Missing: {', '.join(result.missing_information) or 'none'}"}, reason="Record qualification rationale", risk_level="low"))

        result.data = LeadOut(
            lead_id=lead_id, normalized_lead={k: v for k, v in lead.items() if k != "email_invalid"}, score=score, score_breakdown=breakdown, qualified=qualified,
            tier=tier, assigned_team=assigned, routing_reason=reason, duplicate_of=duplicate_of, missing_fields=result.missing_information,
            follow_up_questions=questions, protected_attributes_ignored=sorted(removed), extracted_need=need.need_summary,
        ).model_dump()
        result.summary = f"{lead.get('name') or lead.get('email') or 'Lead'} scored {score}/100 (tier {tier}) → {'qualified' if qualified else status}" + (f", routed to {assigned}" if assigned else "") + (" [duplicate merged]" if duplicate_of else "")
        result.confidence = round(1 - len(result.missing_information) / 8, 2)
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved
        return result

    @staticmethod
    def _route(lead: dict[str, Any], score: float, teams: list[dict[str, Any]]) -> tuple[str | None, str | None]:
        size = lead.get("company_size") or 0
        country = str(lead.get("country") or "").upper()
        for team in sorted(teams, key=lambda t: t.get("priority", 99)):
            rules = team.get("rules", {})
            if rules.get("min_company_size") and size < rules["min_company_size"]:
                continue
            if rules.get("max_company_size") and size > rules["max_company_size"]:
                continue
            if rules.get("countries") and country not in rules["countries"]:
                continue
            if rules.get("min_score") and score < rules["min_score"]:
                continue
            return team.get("name"), f"Matched routing rules of team '{team.get('name')}'"
        return None, "No routing rule matched; left unassigned for manual triage"
