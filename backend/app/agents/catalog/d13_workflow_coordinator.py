"""Agent 13 - Workflow Coordinator.

Tracks tasks, dependencies and blockers; identifies overdue and at-risk work
purely from timestamps and SLA rules; proposes owner notifications and
escalations (approval-gated). It never invents owners or deadlines - tasks
without them are listed as needing clarification.
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


class CoordinatorIn(AgentInput):
    scope: str = Field(default="all", description="all | overdue | recent")
    source_run_id: str | None = None
    at_risk_hours: int = Field(default=24, ge=1, le=240)
    notify_channel: str = "#ops"


class TaskIssue(BaseModel):
    task_id: str
    title: str
    owner: str | None
    due_at: str | None
    status: str
    issue: str
    hours_overdue: float | None = None
    blocked_by: list[str] = Field(default_factory=list)
    escalation_level: int


class CoordinatorOut(BaseModel):
    tasks_reviewed: int
    overdue: list[TaskIssue]
    at_risk: list[TaskIssue]
    blocked: list[TaskIssue]
    unassigned_or_undated: list[TaskIssue]
    notifications_proposed: int
    rules: dict[str, Any]


@register
class WorkflowCoordinatorAgent(BaseAgent):
    spec = AgentSpec(
        key="workflow_coordinator",
        name="Workflow Coordinator Agent",
        department="operations",
        version="1.0.2",
        description="Tracks tasks, dependencies and blockers, flags overdue work by deterministic SLA rules and coordinates owner notifications and escalations.",
        use_cases=["Daily stand-up digest", "Overdue escalation", "Dependency tracking"],
        input_model=CoordinatorIn,
        output_model=CoordinatorOut,
        allowed_tools=["platform.list_tasks", "chat.post_message", "platform.escalate_task", "platform.create_task"],
        permission_scopes=["tasks:read", "tasks:write", "chat:write"],
        policies=["deterministic_deadlines", "no_invented_owners", "escalation_requires_approval"],
        approval_rules=[ApprovalRule(action_type="task.escalate", condition="escalations notify managers")],
        timeout_seconds=60,
        token_budget=2000,
        risk_level="low",
        baseline_minutes_saved=15,
    )

    def run(self, ctx: AgentContext, payload: CoordinatorIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        tasks = services.tools.call("platform.list_tasks", limit=500).get("items", [])
        if payload.scope == "recent" and payload.source_run_id:
            tasks = [t for t in tasks if (parse_dt(t.get("created_at")) or ctx.now) >= ctx.now - timedelta(hours=2)]
        open_tasks = [t for t in tasks if t.get("status") not in {"done", "cancelled"}]
        by_id = {t["id"]: t for t in tasks}
        overdue: list[TaskIssue] = []
        at_risk: list[TaskIssue] = []
        blocked: list[TaskIssue] = []
        undated: list[TaskIssue] = []
        for t in open_tasks:
            due = parse_dt(t.get("due_at"))
            owner = t.get("owner_name")
            deps = [d for d in (t.get("depends_on") or []) if d in by_id and by_id[d].get("status") not in {"done", "cancelled"}]
            base = dict(task_id=t["id"], title=t["title"], owner=owner, due_at=t.get("due_at"), status=t.get("status"), escalation_level=int(t.get("escalation_level") or 0))
            if not owner or not due:
                undated.append(TaskIssue(**base, issue="Missing " + " and ".join(x for x, ok in (("owner", not owner), ("deadline", not due)) if ok) + " — needs clarification (not inferred)"))
                result.missing_information.append(f"Task '{t['title']}': " + ("owner" if not owner else "") + (" & " if not owner and not due else "") + ("deadline" if not due else ""))
            if deps or t.get("status") == "blocked":
                blocked.append(TaskIssue(**base, issue="Blocked by open dependencies" if deps else "Marked blocked", blocked_by=deps))
            if due:
                if due < ctx.now:
                    hrs = round((ctx.now - due).total_seconds() / 3600, 1)
                    overdue.append(TaskIssue(**base, issue=f"Overdue by {hrs}h", hours_overdue=hrs))
                elif due <= ctx.now + timedelta(hours=payload.at_risk_hours):
                    at_risk.append(TaskIssue(**base, issue=f"Due within {payload.at_risk_hours}h"))
            result.add_evidence(f"task:{t['id']}", excerpt=f"{t['title']} due={t.get('due_at')} owner={owner}", source_type="task")
        overdue.sort(key=lambda x: -(x.hours_overdue or 0))
        if payload.scope == "overdue":
            at_risk = []

        notifications = 0
        for o in overdue:
            level = 2 if (o.hours_overdue or 0) >= 48 else 1
            if o.escalation_level < level and o.owner:
                result.proposed_actions.append(ProposedAction(action_type="task.escalate", tool_key="platform.escalate_task", payload={"task_id": o.task_id, "level": level, "note": f"{o.issue}; owner {o.owner}"}, reason=f"Escalate L{level}: {o.title}", risk_level="medium", evidence_refs=[f"task:{o.task_id}"], estimated_minutes_saved=3))
                notifications += 1
        if overdue or at_risk or blocked:
            lines = [f"*Coordinator digest* — {len(overdue)} overdue, {len(at_risk)} at risk, {len(blocked)} blocked"]
            lines += [f"• OVERDUE {o.title} ({o.owner or 'unassigned'}, {o.issue})" for o in overdue[:8]]
            lines += [f"• AT RISK {a.title} ({a.owner or 'unassigned'}, due {a.due_at})" for a in at_risk[:5]]
            lines += [f"• BLOCKED {b.title} ← {', '.join(by_id[d]['title'] for d in b.blocked_by[:3]) or b.issue}" for b in blocked[:5]]
            result.proposed_actions.append(ProposedAction(action_type="chat.notify", tool_key="chat.post_message", payload={"channel": payload.notify_channel, "text": "\n".join(lines)}, reason="Notify owners per policy", risk_level="low", evidence_refs=result.evidence_refs[:5], estimated_minutes_saved=5))
            notifications += 1
        result.data = CoordinatorOut(tasks_reviewed=len(open_tasks), overdue=overdue, at_risk=at_risk, blocked=blocked, unassigned_or_undated=undated, notifications_proposed=notifications, rules={"overdue": "due_at < now", "at_risk_hours": payload.at_risk_hours, "escalation": {"L1": ">0h overdue", "L2": ">=48h overdue"}}).model_dump()
        result.summary = f"{len(open_tasks)} open task(s): {len(overdue)} overdue, {len(at_risk)} at risk, {len(blocked)} blocked, {len(undated)} need owner/deadline"
        result.confidence = 1.0
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved if open_tasks else 0
        return result
