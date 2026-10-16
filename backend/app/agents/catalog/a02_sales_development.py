"""Agent 2 - AI Sales Development.

Researches a prospect using only authorised sources (CRM record, activity
history, tenant knowledge base), drafts personalised outreach grounded in
verified facts, and maintains follow-up schedules. Respects consent,
unsubscribes and contact-frequency limits. Sending always requires approval
unless a narrow tenant auto-approve policy matches.
"""

from __future__ import annotations

from datetime import timedelta
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
from app.agents.common import parse_dt
from app.agents.registry import register
from app.agents.services import AgentServices
from app.core.errors import NotFound
from app.llm.safety import find_unsupported_references


class SDRIn(AgentInput):
    lead_id: str | None = None
    lead: dict[str, Any] | None = None
    qualification: dict[str, Any] | None = None
    goal: str = Field(default="book a 20-minute discovery call")
    sender_name: str = Field(default="The OpsPilot team")


class VerifiedFact(BaseModel):
    ref: str
    fact: str


class PersonalizationPoint(BaseModel):
    claim: str
    evidence_ref: str


class OutreachDraft(BaseModel):
    subject: str = Field(max_length=120)
    body: str = Field(max_length=4000)
    personalization_points: list[PersonalizationPoint] = Field(default_factory=list)


class SDROut(BaseModel):
    lead_id: str | None
    eligible_to_contact: bool
    blocked_reason: str | None = None
    verified_facts: list[VerifiedFact]
    draft: OutreachDraft | None = None
    followup_schedule: list[str] = Field(default_factory=list)
    contacts_last_7_days: int = 0


@register
class SalesDevelopmentAgent(BaseAgent):
    spec = AgentSpec(
        key="sales_development",
        name="AI Sales Development Agent",
        department="sales_revenue",
        version="1.1.0",
        description="Researches prospects from authorised sources, drafts verified personalised outreach and maintains compliant follow-up cadences.",
        use_cases=["First-touch outreach", "Follow-up cadences", "CRM hygiene after outreach"],
        input_model=SDRIn,
        output_model=SDROut,
        allowed_tools=["crm.get_lead", "crm.get_activity", "crm.check_consent", "platform.search_knowledge", "email.send", "crm.log_activity", "crm.schedule_followup"],
        permission_scopes=["crm:read", "crm:write", "email:send", "documents:read"],
        policies=["consent_required", "unsubscribe_respected", "contact_frequency_limit", "verified_personalization_only", "external_send_requires_approval"],
        approval_rules=[ApprovalRule(action_type="email.send", condition="all outbound prospect emails", required_permission="email:send")],
        timeout_seconds=90,
        token_budget=10000,
        risk_level="high",
        baseline_minutes_saved=15,
    )

    def run(self, ctx: AgentContext, payload: SDRIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        lead: dict[str, Any] = {}
        if payload.lead_id:
            try:
                lead = services.tools.call("crm.get_lead", lead_id=payload.lead_id)
                result.add_evidence(f"crm:lead:{payload.lead_id}", excerpt=f"{lead.get('name')} · {lead.get('title')} · {lead.get('company')}", source_type="crm")
            except NotFound:
                result.warnings.append(f"Lead {payload.lead_id} not found in CRM; using provided lead data only")
        if not lead and payload.lead:
            lead = dict(payload.lead)
            result.add_evidence("input:lead", excerpt=str({k: lead.get(k) for k in ('name', 'company', 'title')}), source_type="input")
        lead_id = payload.lead_id or lead.get("id")
        email = lead.get("email")
        if not email:
            result.status = "needs_input"
            result.missing_information = ["lead email address"]
            result.data = SDROut(lead_id=lead_id, eligible_to_contact=False, blocked_reason="No email address on record", verified_facts=[]).model_dump()
            result.summary = "Cannot draft outreach: no verified email address"
            return result

        # --- Consent and frequency limits (deterministic) -------------------
        consent = services.tools.call("crm.check_consent", email=email)
        max_per_week = int(ctx.agent_config.get("max_contacts_per_7_days", 2))
        activity = services.tools.call("crm.get_activity", lead_id=lead_id) if lead_id else {"items": []}
        recent = [a for a in activity.get("items", []) if a.get("type") in {"outreach", "email"} and (parse_dt(a.get("at")) or ctx.now) >= ctx.now - timedelta(days=7)]
        blocked = None
        if consent.get("unsubscribed") or consent.get("do_not_contact"):
            blocked = "Prospect has unsubscribed or is marked do-not-contact"
        elif len(recent) >= max_per_week:
            blocked = f"Contact frequency limit reached ({len(recent)} in last 7 days, max {max_per_week})"
        require_opt_in = bool(ctx.agent_config.get("require_marketing_opt_in", False))
        if not blocked and require_opt_in and not consent.get("marketing_opt_in"):
            blocked = "Tenant policy requires explicit marketing opt-in, which is not on record"
        result.add_evidence(f"crm:consent:{email}", excerpt=f"opt_in={consent.get('marketing_opt_in')} unsubscribed={consent.get('unsubscribed')}", source_type="crm")

        # --- Verified facts (authorised sources only) ------------------------
        facts: list[VerifiedFact] = []
        src = f"crm:lead:{lead_id}" if payload.lead_id and lead else "input:lead"
        for key, label in (("company", "Works at"), ("title", "Role"), ("industry", "Industry"), ("company_size", "Company size"), ("country", "Country")):
            if lead.get(key):
                facts.append(VerifiedFact(ref=src, fact=f"{label}: {lead[key]}"))
        if lead.get("message"):
            facts.append(VerifiedFact(ref=src, fact=f"Stated need: {str(lead['message'])[:240]}"))
        if payload.qualification and payload.qualification.get("extracted_need"):
            facts.append(VerifiedFact(ref="workflow:qualification", fact=f"Qualified need: {payload.qualification['extracted_need']}"))
            result.add_evidence("workflow:qualification", excerpt=str(payload.qualification.get("score")), source_type="workflow")
        query = " ".join(filter(None, [str(lead.get("industry") or ""), str(lead.get("message") or "")[:200], "case study"]))
        kb = services.tools.call("platform.search_knowledge", query=query, collection="sales", limit=2) if query.strip() else {"items": []}
        for hit in kb.get("items", []):
            facts.append(VerifiedFact(ref=hit["ref"], fact=f"Relevant material '{hit['document_name']}': {hit['text'][:220]}"))
            result.add_evidence(hit["ref"], excerpt=hit["text"][:200], source_type="knowledge_base")

        if blocked:
            result.data = SDROut(lead_id=lead_id, eligible_to_contact=False, blocked_reason=blocked, verified_facts=facts, contacts_last_7_days=len(recent)).model_dump()
            result.summary = f"Outreach blocked: {blocked}"
            result.warnings.append(blocked)
            return result

        known_refs = {f.ref for f in facts}
        first = lead.get("first_name") or str(lead.get("name") or "there").split()[0]

        def heuristic() -> OutreachDraft:
            company = lead.get("company") or "your team"
            need = (payload.qualification or {}).get("extracted_need") or lead.get("message")
            hook = f"You mentioned: \"{str(need)[:140]}\"." if need else f"I noticed {company} is in {lead.get('industry') or 'a fast-moving space'}."
            proof = ""
            if kb.get("items"):
                proof = f"\n\nWe recently documented how a similar team approached this (\"{kb['items'][0]['document_name']}\")."
            points = [PersonalizationPoint(claim=f"Works at {company}", evidence_ref=src)] if lead.get("company") else []
            if need:
                points.append(PersonalizationPoint(claim="Stated need", evidence_ref=src if lead.get("message") else "workflow:qualification"))
            return OutreachDraft(
                subject=f"{company} + OpsPilot: quick idea"[:120],
                body=f"Hi {first},\n\n{hook} OpsPilot helps operations teams automate routine work with approval-gated AI agents.{proof}\n\nWould you be open to {payload.goal} next week?\n\nBest,\n{payload.sender_name}",
                personalization_points=points,
            )

        facts_block = "\n".join(f"[{f.ref}] {f.fact}" for f in facts)
        draft = services.structured(
            task="sdr_outreach_draft",
            schema=OutreachDraft,
            system=(
                "You write concise, respectful B2B outreach emails. Use ONLY the verified facts provided; every personalised claim "
                "must cite the evidence_ref of the fact it relies on. Never invent metrics, customers, mutual connections or events. "
                f"Goal: {payload.goal}. Sign as {payload.sender_name}. No more than 120 words."
            ),
            user=f"Verified facts:\n{facts_block}\n\nProspect first name: {first}",
            heuristic=heuristic,
        )
        # Enforce grounding deterministically.
        grounded = [p for p in draft.personalization_points if p.evidence_ref in known_refs]
        dropped = len(draft.personalization_points) - len(grounded)
        if dropped:
            result.warnings.append(f"Removed {dropped} personalisation claim(s) without verified evidence")
        draft.personalization_points = grounded
        unsupported = find_unsupported_references(draft.body, [facts_block, payload.sender_name])
        if unsupported:
            result.warnings.append(f"Unsupported links/contacts removed from draft: {', '.join(unsupported)}")
            for u in unsupported:
                draft.body = draft.body.replace(u, "[removed]")
        unsubscribe = ctx.agent_config.get("unsubscribe_footer", "If you'd prefer not to hear from us, reply 'unsubscribe' and we won't contact you again.")
        if unsubscribe not in draft.body:
            draft.body = f"{draft.body.rstrip()}\n\n{unsubscribe}"

        cadence_days = list(ctx.agent_config.get("followup_days", [3, 7]))
        schedule = [(ctx.now + timedelta(days=d)).date().isoformat() for d in cadence_days]
        result.proposed_actions.append(ProposedAction(action_type="email.send", tool_key="email.send", payload={"to": email, "subject": draft.subject, "body": draft.body}, reason=f"First-touch outreach to {lead.get('name') or email}", risk_level="high", evidence_refs=[p.evidence_ref for p in grounded], estimated_minutes_saved=10))
        if lead_id:
            result.proposed_actions.append(ProposedAction(action_type="crm.log_activity", tool_key="crm.log_activity", payload={"lead_id": lead_id, "activity_type": "outreach_drafted", "note": f"Drafted outreach '{draft.subject}' pending approval"}, reason="Keep CRM history current", risk_level="low"))
            for day in schedule[:1]:
                result.proposed_actions.append(ProposedAction(action_type="crm.schedule_followup", tool_key="crm.schedule_followup", payload={"lead_id": lead_id, "at": day, "note": "Follow up if no reply to first-touch email"}, reason="Maintain follow-up cadence", risk_level="low"))

        result.data = SDROut(lead_id=lead_id, eligible_to_contact=True, verified_facts=facts, draft=draft, followup_schedule=schedule, contacts_last_7_days=len(recent)).model_dump()
        result.summary = f"Drafted grounded outreach to {lead.get('name') or email} ({len(grounded)} verified personalisation points); sending awaits approval"
        result.confidence = 0.8 if grounded else 0.6
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved
        return result
