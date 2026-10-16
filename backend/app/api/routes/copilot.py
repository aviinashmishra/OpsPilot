"""Ops Copilot API: chat sessions whose turns run as background jobs with live tool-call steps."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import AfterValidator, BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.copilot import service
from app.copilot.tools import CopilotToolbox
from app.core.errors import AuthorizationError
from app.core.ratelimit import check_rate_limit
from app.db.models import CopilotMessage, CopilotSession
from app.db.session import get_db
from app.llm.gateway import get_gateway

router = APIRouter(prefix="/copilot", tags=["copilot"])

# SQLite hands back naive datetimes (they are UTC); always serialise with an explicit offset.
UTCDateTime = Annotated[datetime, AfterValidator(lambda d: d if d.tzinfo else d.replace(tzinfo=UTC))]


class CopilotMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class StepOut(BaseModel):
    id: str
    sequence: int
    iteration: int
    tool_name: str
    kind: str
    label: str
    input: dict[str, Any]
    output: dict[str, Any]
    summary: str | None
    status: str
    duration_ms: int | None
    approval_ids: list[str]
    agent_run_id: str | None
    workflow_run_id: str | None
    created_at: UTCDateTime


class MessageOut(BaseModel):
    id: str
    sequence: int
    role: str
    text: str
    status: str
    mode: str | None
    model: str | None
    usage: dict[str, Any]
    error: str | None
    created_at: UTCDateTime
    finished_at: UTCDateTime | None
    steps: list[StepOut]


class SessionOut(BaseModel):
    id: str
    title: str
    correlation_id: str
    cost_usd: float
    tokens: int
    created_at: UTCDateTime
    updated_at: UTCDateTime
    busy: bool = False
    messages: list[MessageOut] = Field(default_factory=list)


def _user(principal: Principal):  # type: ignore[no-untyped-def]
    if principal.user is None:
        raise AuthorizationError("The Copilot is available to signed-in users (use the MCP endpoint for API keys)")
    return principal.user


def _session_out(s: CopilotSession, with_messages: bool = True) -> SessionOut:
    msgs = [
        MessageOut(
            id=str(m.id), sequence=m.sequence, role=m.role, text=m.text, status=m.status, mode=m.mode, model=m.model, usage=m.usage or {}, error=m.error, created_at=m.created_at, finished_at=m.finished_at,
            steps=[StepOut(id=str(st.id), sequence=st.sequence, iteration=st.iteration, tool_name=st.tool_name, kind=st.kind, label=st.label, input=st.input or {}, output=st.output or {}, summary=st.summary, status=st.status, duration_ms=st.duration_ms, approval_ids=st.approval_ids or [], agent_run_id=str(st.agent_run_id) if st.agent_run_id else None, workflow_run_id=str(st.workflow_run_id) if st.workflow_run_id else None, created_at=st.created_at) for st in m.steps],
        )
        for m in s.messages
    ] if with_messages else []
    busy = any(m.status in {"pending", "running"} for m in s.messages) if with_messages else False
    return SessionOut(id=str(s.id), title=s.title, correlation_id=s.correlation_id, cost_usd=s.cost_usd, tokens=s.tokens, created_at=s.created_at, updated_at=s.updated_at, busy=busy, messages=msgs)


@router.get("/status", summary="Copilot mode and the tools available to the current user")
def copilot_status(principal: Principal = Depends(require("agents:run")), db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _user(principal)
    perms = sorted({p for r in user.roles for p in (r.permissions or [])})
    tools = CopilotToolbox(db, principal.tenant, str(user.id), perms, "status").build()
    gw = get_gateway()
    counts: dict[str, int] = {}
    for t in tools:
        counts[t.kind] = counts.get(t.kind, 0) + 1
    return {
        "mode": gw.copilot_mode,
        "model": None if gw.copilot_mode == "offline_planner" else gw.resolve_model("default"),
        "provider": gw.provider.name,
        "tool_counts": counts,
        "tools": [{"name": t.name, "kind": t.kind, "label": t.label, "description": t.description[:300]} for t in tools],
        "suggestions": [
            "What needs my approval right now?",
            "Check inventory and tell me what to reorder",
            "Which tasks are overdue, and who owns them?",
            "Where is order ORD-5002 and is anything wrong with it?",
            "Give me this fortnight's KPI report",
            "Which customers are at risk of churning?",
            "Did the latest checkout-api release cause problems?",
            "Compare the supplier quotes for RFQ-42",
        ],
    }


@router.get("/sessions", response_model=list[SessionOut], summary="My Copilot sessions")
def list_sessions(limit: int = Query(30, ge=1, le=100), principal: Principal = Depends(require("agents:run")), db: Session = Depends(get_db)) -> list[SessionOut]:
    user = _user(principal)
    rows = db.execute(select(CopilotSession).where(CopilotSession.tenant_id == principal.tenant.id, CopilotSession.user_id == user.id).order_by(CopilotSession.updated_at.desc()).limit(limit)).scalars().all()
    busy_ids = set(db.execute(select(CopilotMessage.session_id).where(CopilotMessage.tenant_id == principal.tenant.id, CopilotMessage.status.in_(["pending", "running"]))).scalars().all())
    out = []
    for s in rows:
        so = _session_out(s, with_messages=False)
        so.busy = s.id in busy_ids
        out.append(so)
    return out


@router.post("/sessions", response_model=SessionOut, status_code=202, summary="Start a conversation (the turn runs in the background)")
def create_session(body: CopilotMessageIn, principal: Principal = Depends(require("agents:run")), db: Session = Depends(get_db)) -> SessionOut:
    check_rate_limit(f"copilot:{principal.tenant.id}", limit=120)
    s = service.start_session(db, tenant=principal.tenant, user=_user(principal), text=body.message)
    db.expire_all()
    return _session_out(db.get(CopilotSession, s.id))  # type: ignore[arg-type]


@router.get("/sessions/{session_id}", response_model=SessionOut, summary="Session with messages and live tool-call steps (poll while busy)")
def get_session(session_id: str, principal: Principal = Depends(require("agents:run")), db: Session = Depends(get_db)) -> SessionOut:
    return _session_out(service.get_session(db, tenant=principal.tenant, user=_user(principal), session_id=session_id))


@router.post("/sessions/{session_id}/messages", response_model=SessionOut, status_code=202, summary="Send a follow-up message")
def send_message(session_id: str, body: CopilotMessageIn, principal: Principal = Depends(require("agents:run")), db: Session = Depends(get_db)) -> SessionOut:
    check_rate_limit(f"copilot:{principal.tenant.id}", limit=120)
    s = service.post_message(db, tenant=principal.tenant, user=_user(principal), session_id=session_id, text=body.message)
    db.expire_all()
    return _session_out(db.get(CopilotSession, s.id))  # type: ignore[arg-type]


@router.delete("/sessions/{session_id}", status_code=204, summary="Delete a session", response_model=None)
def delete_session(session_id: str, principal: Principal = Depends(require("agents:run")), db: Session = Depends(get_db)) -> None:
    s = service.get_session(db, tenant=principal.tenant, user=_user(principal), session_id=session_id)
    db.delete(s)
    db.commit()


func  # noqa: B018
