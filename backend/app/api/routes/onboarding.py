"""Getting-started checklist for a workspace. Every step is derived from real activity, so it
completes itself as people use the product (nothing to tick manually)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.db.models import AgentRun, Approval, CopilotSession, Integration, User, WorkflowRun
from app.db.session import get_db
from app.llm.gateway import get_gateway

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("", summary="Getting-started checklist for the current workspace")
def onboarding(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> dict[str, Any]:
    tid = principal.tenant.id

    def has(stmt: Any) -> bool:
        return bool(db.execute(select(exists(stmt))).scalar())

    ai = get_gateway().ai_status()
    steps = [
        {"key": "copilot", "title": "Ask the Copilot a question", "description": "Try “What needs my approval right now?”", "href": "/copilot", "done": has(select(CopilotSession.id).where(CopilotSession.tenant_id == tid))},
        {"key": "agent", "title": "Run an agent on sample data", "description": "Open any agent and press Run in its Playground.", "href": "/agents", "done": has(select(AgentRun.id).where(AgentRun.tenant_id == tid))},
        {"key": "workflow", "title": "Start a workflow", "description": "Chain agents into a process, e.g. new lead → CRM → outreach.", "href": "/workflows", "done": has(select(WorkflowRun.id).where(WorkflowRun.tenant_id == tid, ~WorkflowRun.workflow_key.like("single_agent__%")))},
        {"key": "approval", "title": "Review an approval", "description": "Approve or reject an action an agent proposed.", "href": "/approvals", "done": has(select(Approval.id).where(Approval.tenant_id == tid, Approval.status != "pending"))},
        {"key": "connect", "title": "Connect a real system", "description": "Switch a system such as HubSpot, Slack or Zendesk from sandbox to live.", "href": "/integrations", "done": has(select(Integration.id).where(Integration.tenant_id == tid, Integration.mode == "live"))},
        {"key": "team", "title": "Invite a teammate", "description": "Add people with the right role, e.g. an approver.", "href": "/admin?tab=users", "done": (db.execute(select(func.count()).select_from(User).where(User.tenant_id == tid)).scalar_one() or 0) > 1},
    ]
    done = sum(1 for s in steps if s["done"])
    return {
        "steps": steps,
        "done": done,
        "total": len(steps),
        "complete": done == len(steps),
        "ai": {"available": ai["available"], "configured": bool(ai["routes"]), "next_available_at": ai["next_available_at"]},
        "sandbox": not has(select(Integration.id).where(Integration.tenant_id == tid, Integration.mode == "live")),
    }
