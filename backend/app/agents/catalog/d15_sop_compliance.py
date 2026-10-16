"""Agent 15 - SOP Compliance.

Compares operational records with approved SOPs step by step. Findings cite
the SOP section; confirmed violations (required step missing / out of order
with evidence) are separated from potential concerns (optional steps,
timing anomalies, outdated SOP). Significant findings are escalated.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentResult, AgentSpec, BaseAgent, ProposedAction
from app.agents.common import parse_dt
from app.agents.registry import register
from app.agents.services import AgentServices


class SOPIn(AgentInput):
    process: str | None = None
    record_ids: list[str] | None = None
    sop_review_days: int = Field(default=365, ge=30, le=1825)


class Finding(BaseModel):
    record_id: str
    process: str
    kind: str  # confirmed_violation | potential_concern | outdated_sop
    step: str | None
    policy_ref: str
    detail: str
    severity: str


class SOPOut(BaseModel):
    records_checked: int
    sops_checked: int
    confirmed_violations: list[Finding]
    potential_concerns: list[Finding]
    outdated_sops: list[Finding]
    compliance_rate: float | None
    escalated: bool


@register
class SOPComplianceAgent(BaseAgent):
    spec = AgentSpec(
        key="sop_compliance",
        name="SOP Compliance Agent",
        department="operations",
        version="1.0.1",
        description="Audits operational records against approved SOPs, cites the policy section for every finding and separates confirmed violations from potential concerns.",
        use_cases=["Process audits", "Onboarding checklists", "SOP freshness review"],
        input_model=SOPIn,
        output_model=SOPOut,
        allowed_tools=["metrics.list_sops", "metrics.operational_records", "platform.create_task", "platform.open_incident"],
        permission_scopes=["metrics:read", "tasks:write", "incidents:write"],
        policies=["cite_policy_section", "confirmed_vs_potential", "escalate_significant"],
        timeout_seconds=90,
        token_budget=2000,
        risk_level="low",
        baseline_minutes_saved=35,
    )

    def run(self, ctx: AgentContext, payload: SOPIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        sops = services.tools.call("metrics.list_sops", process=payload.process).get("items", [])
        records = services.tools.call("metrics.operational_records", process=payload.process).get("items", [])
        if payload.record_ids:
            records = [r for r in records if r.get("id") in set(payload.record_ids)]
        sop_by_process = {s["process"]: s for s in sops}
        confirmed: list[Finding] = []
        concerns: list[Finding] = []
        outdated: list[Finding] = []
        for s in sops:
            updated = parse_dt(s.get("last_reviewed_at"))
            ref = f"sop:{s['id']}"
            result.add_evidence(ref, excerpt=f"{s.get('title')} v{s.get('version')}", source_type="policy")
            if updated and ctx.now - updated > timedelta(days=payload.sop_review_days):
                outdated.append(Finding(record_id="-", process=s["process"], kind="outdated_sop", step=None, policy_ref=f"{ref}#metadata", detail=f"SOP last reviewed {updated.date()} (> {payload.sop_review_days} days ago); review recommended", severity="low"))
            elif updated is None:
                outdated.append(Finding(record_id="-", process=s["process"], kind="outdated_sop", step=None, policy_ref=f"{ref}#metadata", detail="SOP has no last-review date on record", severity="low"))
        checked = 0
        for r in records:
            sop = sop_by_process.get(r.get("process"))
            if not sop:
                concerns.append(Finding(record_id=r["id"], process=r.get("process", "?"), kind="potential_concern", step=None, policy_ref="sop:none", detail="No approved SOP exists for this process", severity="medium"))
                continue
            checked += 1
            done = {e.get("step"): e for e in r.get("steps", [])}
            order = [e.get("step") for e in sorted(r.get("steps", []), key=lambda e: parse_dt(e.get("at")) or ctx.now)]
            prev_idx = -1
            for i, step in enumerate(sop.get("steps", [])):
                key, sec = step["key"], f"sop:{sop['id']}#{step.get('section', i + 1)}"
                base = dict(record_id=r["id"], process=r.get("process", "?"), step=key, policy_ref=sec)
                if key not in done:
                    if step.get("required", True):
                        confirmed.append(Finding(**base, kind="confirmed_violation", detail=f"Required step '{step.get('title', key)}' has no execution record", severity="high" if step.get("critical") else "medium"))
                    else:
                        concerns.append(Finding(**base, kind="potential_concern", detail=f"Optional step '{step.get('title', key)}' not recorded", severity="low"))
                    continue
                idx = order.index(key) if key in order else -1
                if idx != -1 and idx < prev_idx and step.get("ordered", True):
                    confirmed.append(Finding(**base, kind="confirmed_violation", detail=f"Step '{key}' executed before a preceding required step (order violation)", severity="medium"))
                prev_idx = max(prev_idx, idx)
                e = done[key]
                if step.get("max_hours_after_previous") and i > 0:
                    prev_key = sop["steps"][i - 1]["key"]
                    if prev_key in done:
                        t1, t2 = parse_dt(done[prev_key].get("at")), parse_dt(e.get("at"))
                        if t1 and t2 and (t2 - t1) > timedelta(hours=step["max_hours_after_previous"]):
                            concerns.append(Finding(**base, kind="potential_concern", detail=f"Step '{key}' completed {(t2 - t1).total_seconds() / 3600:.1f}h after '{prev_key}' (limit {step['max_hours_after_previous']}h)", severity="medium"))
                if step.get("requires_approval") and not e.get("approved_by"):
                    confirmed.append(Finding(**base, kind="confirmed_violation", detail=f"Step '{key}' requires an approver; none recorded", severity="high"))
                if step.get("required_fields"):
                    missing = [f for f in step["required_fields"] if not e.get(f)]
                    if missing:
                        concerns.append(Finding(**base, kind="potential_concern", detail=f"Step '{key}' record missing fields: {', '.join(missing)}", severity="low"))
            result.add_evidence(f"record:{r['id']}", excerpt=f"{len(r.get('steps', []))} step(s)", source_type="operational_record")
        violating = {f.record_id for f in confirmed}
        rate = round(1 - len(violating) / checked, 4) if checked else None
        escalated = any(f.severity == "high" for f in confirmed) or (checked >= 5 and rate is not None and rate < 0.8)
        if escalated:
            result.proposed_actions.append(ProposedAction(action_type="platform.open_incident", tool_key="platform.open_incident", payload={"title": f"SOP compliance: {len(confirmed)} confirmed violation(s) in {payload.process or 'all processes'}", "severity": "high", "kind": "policy_violation", "details": {"confirmed": [f.model_dump() for f in confirmed[:20]], "compliance_rate": rate}}, reason="Significant findings require human review", risk_level="low", evidence_refs=[f.policy_ref for f in confirmed[:5]], estimated_minutes_saved=10))
        for f in confirmed:
            result.proposed_actions.append(ProposedAction(action_type="platform.create_task", tool_key="platform.create_task", payload={"title": f"SOP violation: {f.process} / {f.step} (record {f.record_id})", "description": f"{f.detail}\nPolicy: {f.policy_ref}", "priority": "high" if f.severity == "high" else "medium", "labels": ["sop", "compliance"], "evidence_refs": [f.policy_ref, f"record:{f.record_id}"]}, reason="Remediation task", risk_level="low", evidence_refs=[f.policy_ref]))
        result.data = SOPOut(records_checked=checked, sops_checked=len(sops), confirmed_violations=confirmed, potential_concerns=concerns, outdated_sops=outdated, compliance_rate=rate, escalated=escalated).model_dump()
        result.summary = f"{checked} record(s) vs {len(sops)} SOP(s): {len(confirmed)} confirmed violation(s), {len(concerns)} potential concern(s), {len(outdated)} outdated SOP(s)" + (f"; compliance {rate:.0%}" if rate is not None else "")
        result.status = "escalated" if escalated else "completed"
        result.confidence = 0.95
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved if checked else 0
        return result


Any  # noqa: B018
