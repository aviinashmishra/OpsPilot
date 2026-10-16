"""Agent directory, configuration, and invocation."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.registry import agent_registry
from app.agents.runner import run_agent
from app.api.deps import Principal, require
from app.api.schemas import (
    AgentCatalogOut,
    AgentDetailOut,
    AgentRunDirectOut,
    AgentRunIn,
    AgentRunOut,
    AgentSettingIn,
    Page,
)
from app.api.serializers import agent_run_out
from app.core.errors import NotFound
from app.core.ratelimit import check_rate_limit
from app.db.models import AgentDefinition, AgentRun, EvaluationResult, TenantAgentSetting, WorkflowDefinition
from app.db.session import get_db
from app.orchestration.engine import start_run
from app.services.audit import record_audit
from app.tools.registry import tool_registry

router = APIRouter(prefix="/agents", tags=["agents"])


def _stats(db: Session, tenant_id: uuid.UUID) -> dict[str, dict]:
    rows = db.execute(
        select(AgentRun.agent_key, AgentRun.status, func.count(), func.sum(AgentRun.cost_usd), func.avg(AgentRun.latency_ms))
        .where(AgentRun.tenant_id == tenant_id)
        .group_by(AgentRun.agent_key, AgentRun.status)
    ).all()
    out: dict[str, dict] = {}
    for key, status, n, cost, lat in rows:
        s = out.setdefault(key, {"runs": 0, "succeeded": 0, "failed": 0, "needs_approval": 0, "cost_usd": 0.0, "avg_latency_ms": 0.0, "_lat": []})
        s["runs"] += n
        s["cost_usd"] = round(s["cost_usd"] + float(cost or 0), 6)
        s["_lat"].append((float(lat or 0), n))
        if status == "completed":
            s["succeeded"] += n
        elif status == "needs_approval":
            s["needs_approval"] += n
            s["succeeded"] += n
        elif status == "failed":
            s["failed"] += n
    for s in out.values():
        tot = sum(n for _, n in s["_lat"]) or 1
        s["avg_latency_ms"] = round(sum(lat * n for lat, n in s["_lat"]) / tot, 1)
        s["success_rate"] = round(s["succeeded"] / s["runs"], 4) if s["runs"] else None
        del s["_lat"]
    return out


def _catalog_entry(spec_dict: dict, definition: AgentDefinition | None, setting: TenantAgentSetting | None, stats: dict, emergency: bool) -> dict:
    globally = definition.is_globally_enabled if definition else True
    tenant_enabled = setting.enabled if setting else True
    return {
        **{k: v for k, v in spec_dict.items() if k not in {"input_schema", "output_schema"}},
        "enabled": bool(globally and tenant_enabled and not emergency),
        "globally_enabled": globally,
        "tenant_config": setting.config if setting else {},
        "model_override": setting.model_override if setting else None,
        "disabled_reason": ("Tenant emergency disable active" if emergency else (setting.disabled_reason if setting and not setting.enabled else None)),
        "stats": stats.get(spec_dict["agent_key"], {"runs": 0, "succeeded": 0, "failed": 0, "needs_approval": 0, "cost_usd": 0.0, "avg_latency_ms": 0.0, "success_rate": None}),
    }


@router.get("", response_model=list[AgentCatalogOut], summary="List all registered agents")
def list_agents(department: str | None = None, q: str | None = None, principal: Principal = Depends(require("agents:read")), db: Session = Depends(get_db)) -> list[AgentCatalogOut]:
    defs = {d.agent_key: d for d in db.execute(select(AgentDefinition)).scalars().all()}
    settings = {s.agent_key: s for s in db.execute(select(TenantAgentSetting).where(TenantAgentSetting.tenant_id == principal.tenant.id)).scalars().all()}
    stats = _stats(db, principal.tenant.id)
    out = []
    for spec in agent_registry.catalog():
        if department and spec["department"] != department:
            continue
        if q and q.lower() not in (spec["name"] + " " + spec["description"]).lower():
            continue
        out.append(AgentCatalogOut(**_catalog_entry(spec, defs.get(spec["agent_key"]), settings.get(spec["agent_key"]), stats, principal.tenant.emergency_disabled)))
    return out


@router.get("/{agent_id}", response_model=AgentDetailOut, summary="Agent detail with contract, tools and recent runs")
def get_agent(agent_id: str, principal: Principal = Depends(require("agents:read")), db: Session = Depends(get_db)) -> AgentDetailOut:
    if not agent_registry.has(agent_id):
        raise NotFound(f"Agent '{agent_id}' not found")
    spec = agent_registry.get(agent_id).spec
    spec_dict = spec.to_catalog_dict()
    definition = db.execute(select(AgentDefinition).where(AgentDefinition.agent_key == agent_id)).scalar_one_or_none()
    setting = db.execute(select(TenantAgentSetting).where(TenantAgentSetting.tenant_id == principal.tenant.id, TenantAgentSetting.agent_key == agent_id)).scalar_one_or_none()
    runs = db.execute(select(AgentRun).where(AgentRun.tenant_id == principal.tenant.id, AgentRun.agent_key == agent_id).order_by(AgentRun.started_at.desc()).limit(10)).scalars().all()
    ev = db.execute(select(EvaluationResult).where(EvaluationResult.agent_key == agent_id).order_by(EvaluationResult.created_at.desc()).limit(1)).scalar_one_or_none()
    entry = _catalog_entry(spec_dict, definition, setting, _stats(db, principal.tenant.id), principal.tenant.emergency_disabled)
    return AgentDetailOut(
        **entry,
        input_schema=spec_dict["input_schema"],
        output_schema=spec_dict["output_schema"],
        tools=[tool_registry.get(t).describe() for t in spec.allowed_tools if tool_registry.has(t)],
        recent_runs=[agent_run_out(r, principal.has("data:sensitive")) for r in runs],
        evaluation={"metrics": ev.metrics, "passed": ev.passed, "created_at": ev.created_at.isoformat(), "model": ev.model, "cases": len(ev.case_results)} if ev else None,
        example_input=_example_input(agent_id),
    )


def _example_input(agent_id: str) -> dict[str, Any] | None:
    from app.evaluation.datasets import DATASETS

    cases = DATASETS.get(agent_id, {}).get("cases") or []
    return copy.deepcopy(cases[0]["input"]) if cases else None


@router.patch("/{agent_id}", response_model=AgentCatalogOut, summary="Enable/disable or configure an agent for this tenant")
def update_agent(agent_id: str, body: AgentSettingIn, principal: Principal = Depends(require("agents:admin")), db: Session = Depends(get_db)) -> AgentCatalogOut:
    if not agent_registry.has(agent_id):
        raise NotFound(f"Agent '{agent_id}' not found")
    setting = db.execute(select(TenantAgentSetting).where(TenantAgentSetting.tenant_id == principal.tenant.id, TenantAgentSetting.agent_key == agent_id)).scalar_one_or_none()
    if setting is None:
        setting = TenantAgentSetting(tenant_id=principal.tenant.id, agent_key=agent_id, enabled=True, config={})
        db.add(setting)
    before = {"enabled": setting.enabled, "config": setting.config, "model_override": setting.model_override}
    if body.enabled is not None:
        setting.enabled = body.enabled
        setting.disabled_reason = body.disabled_reason if not body.enabled else None
    if body.config is not None:
        setting.config = body.config
    if body.model_override is not None:
        setting.model_override = body.model_override or None
    db.flush()
    record_audit(db, tenant_id=principal.tenant.id, action="agent.configured", resource_type="agent", resource_id=agent_id, actor_id=principal.actor_id, details={"before": before, "after": body.model_dump(exclude_none=True)}, severity="warning" if body.enabled is False else "info")
    db.commit()
    definition = db.execute(select(AgentDefinition).where(AgentDefinition.agent_key == agent_id)).scalar_one_or_none()
    return AgentCatalogOut(**_catalog_entry(agent_registry.get(agent_id).spec.to_catalog_dict(), definition, setting, _stats(db, principal.tenant.id), principal.tenant.emergency_disabled))


@router.post("/{agent_id}/run", response_model=AgentRunDirectOut, summary="Invoke an agent through the shared execution framework")
def run_agent_endpoint(
    agent_id: str,
    body: AgentRunIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require("agents:run")),
    db: Session = Depends(get_db),
) -> AgentRunDirectOut:
    if not agent_registry.has(agent_id):
        raise NotFound(f"Agent '{agent_id}' not found")
    check_rate_limit(f"agents:{principal.tenant.id}")
    if body.mode == "workflow":
        # Durable path: wrap in the single_agent workflow so the run is checkpointed and approval-gated.
        key = f"single_agent__{agent_id}"
        _ensure_single_agent_workflow(db, agent_id, key)
        run = start_run(db, tenant_id=str(principal.tenant.id), workflow_key=key, input={"payload": body.input}, actor_id=principal.actor_id, idempotency_key=idempotency_key, enqueue=False, permissions=principal.permissions if not principal.is_admin else None)
        from app.orchestration.engine import execute_run

        if run.status == "pending":
            execute_run(str(run.id))
        db.expire_all()
        ar = db.execute(select(AgentRun).where(AgentRun.run_id == run.id).order_by(AgentRun.started_at.desc())).scalars().first()
        if ar is None:
            from app.api.serializers import run_out

            r = run_out(db.get(type(run), run.id), detailed=True)  # type: ignore[arg-type]
            return AgentRunDirectOut(agent_run_id="", status=r.status, result={"error": r.error}, actions=[], latency_ms=0, usage={}, tool_modes=[], workflow_run_id=str(run.id))
        return AgentRunDirectOut(
            agent_run_id=str(ar.id), status=ar.status,
            result={"data": {k: v for k, v in ar.output.items() if not k.startswith("_")}, "summary": ar.output.get("_summary"), "evidence_refs": ar.evidence_refs, "missing_information": ar.missing_information, "warnings": ar.warnings, "proposed_actions": ar.proposed_actions, "confidence": ar.output.get("_confidence"), "error": ar.error},
            actions=ar.output.get("_actions", []), latency_ms=ar.latency_ms or 0,
            usage={"prompt_tokens": ar.prompt_tokens, "completion_tokens": ar.completion_tokens, "cost_usd": ar.cost_usd, "model": ar.model},
            tool_modes=ar.output.get("_tool_modes", []), workflow_run_id=str(run.id),
        )
    outcome = run_agent(db, tenant=principal.tenant, agent_key=agent_id, input=body.input, actor_id=principal.actor_id, permissions=principal.permissions, correlation_id=uuid.uuid4().hex)
    return AgentRunDirectOut(
        agent_run_id=outcome.agent_run_id, status=outcome.status, result=outcome.result.model_dump(mode="json"),
        actions=[a.model_dump(mode="json", exclude={"decision"}) for a in outcome.actions], latency_ms=outcome.latency_ms, usage=outcome.usage, tool_modes=outcome.tool_modes,
    )


@router.get("/{agent_id}/runs", response_model=Page[AgentRunOut], summary="Agent run history")
def agent_runs(agent_id: str, limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0), principal: Principal = Depends(require("agents:read")), db: Session = Depends(get_db)) -> Page[AgentRunOut]:
    stmt = select(AgentRun).where(AgentRun.tenant_id == principal.tenant.id, AgentRun.agent_key == agent_id)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(AgentRun.started_at.desc()).limit(limit).offset(offset)).scalars().all()
    return Page(items=[agent_run_out(r, principal.has("data:sensitive")) for r in rows], total=total, limit=limit, offset=offset)


def _ensure_single_agent_workflow(db: Session, agent_key: str, key: str) -> None:
    exists = db.execute(select(WorkflowDefinition).where(WorkflowDefinition.key == key, WorkflowDefinition.tenant_id.is_(None))).scalar_one_or_none()
    if exists:
        return
    db.add(
        WorkflowDefinition(
            tenant_id=None, key=key, name=f"Run {agent_registry.get(agent_key).spec.name}", description="Single-agent wrapper (auto-generated)", version=1,
            graph={"start": "run", "nodes": {"run": {"type": "agent", "agent": agent_key, "input": "$.input.payload", "next": "gate"}, "gate": {"type": "approval_gate", "next": "end"}, "end": {"type": "end"}}},
            trigger={"manual": True}, timeout_seconds=300,
        )
    )
    db.commit()
