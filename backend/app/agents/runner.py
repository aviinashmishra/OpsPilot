"""Run a single agent through the shared execution framework.

Responsibilities: enablement checks, input validation, AgentRun persistence,
LLM budget, output validation, evidence checks, action processing (policy +
approvals + execution), usage metering and audit.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.registry import agent_registry
from app.agents.services import AgentServices
from app.core.errors import AgentDisabled, OpsPilotError, ValidationFailed
from app.core.logging import get_logger
from app.db.models import AgentDefinition, AgentRun, Tenant, TenantAgentSetting
from app.llm.gateway import get_gateway
from app.policy.engine import POLICY_VERSION, evaluate_agent_enabled
from app.services.actions import ActionOutcome, ActionService
from app.services.audit import record_audit
from app.services.usage import record_usage

log = get_logger("agent.runner")


class AgentRunOutcome(BaseModel):
    agent_run_id: str
    agent_key: str
    status: str
    result: AgentResult
    actions: list[ActionOutcome]
    latency_ms: int
    usage: dict[str, Any]
    tool_modes: list[str]

    @property
    def pending_approval_ids(self) -> list[str]:
        return [a.approval_id for a in self.actions if a.approval_id]


def _tenant_agent_setting(db: Session, tenant_id: uuid.UUID, agent_key: str) -> TenantAgentSetting | None:
    return db.execute(
        select(TenantAgentSetting).where(TenantAgentSetting.tenant_id == tenant_id, TenantAgentSetting.agent_key == agent_key)
    ).scalar_one_or_none()


def check_agent_enabled(db: Session, tenant: Tenant, agent_key: str) -> tuple[bool, str]:
    definition = db.execute(select(AgentDefinition).where(AgentDefinition.agent_key == agent_key)).scalar_one_or_none()
    setting = _tenant_agent_setting(db, tenant.id, agent_key)
    return evaluate_agent_enabled(
        globally_enabled=definition.is_globally_enabled if definition else True,
        tenant_enabled=setting.enabled if setting else None,
        emergency_disabled=tenant.emergency_disabled,
    )


def run_agent(
    db: Session,
    *,
    tenant: Tenant,
    agent_key: str,
    input: dict[str, Any],
    actor_id: str,
    permissions: list[str],
    correlation_id: str,
    workflow_run_id: str | None = None,
    node_key: str | None = None,
    depth: int = 0,
    execute_actions: bool = True,
    extra_context: dict[str, Any] | None = None,
    idempotency_scope: str | None = None,
) -> AgentRunOutcome:
    agent_cls: type[BaseAgent] = agent_registry.get(agent_key)
    spec = agent_cls.spec

    enabled, why = check_agent_enabled(db, tenant, agent_key)
    if not enabled:
        raise AgentDisabled(f"Agent '{agent_key}' cannot run: {why}")

    try:
        payload = agent_cls.validate_input(input)
    except ValidationError as exc:
        raise ValidationFailed(f"Invalid input for agent '{agent_key}'", details={"errors": exc.errors()[:8]}) from exc

    setting = _tenant_agent_setting(db, tenant.id, agent_key)
    agent_run = AgentRun(
        tenant_id=tenant.id,
        run_id=uuid.UUID(workflow_run_id) if workflow_run_id else None,
        agent_key=agent_key,
        agent_version=spec.version,
        node_key=node_key,
        status="running",
        actor_id=actor_id,
        correlation_id=correlation_id,
        input=payload.model_dump(mode="json"),
    )
    db.add(agent_run)
    db.flush()
    db.commit()

    ctx = AgentContext(
        tenant_id=str(tenant.id),
        actor_id=actor_id,
        workflow_run_id=workflow_run_id,
        agent_run_id=str(agent_run.id),
        correlation_id=correlation_id,
        idempotency_scope=idempotency_scope,
        permissions=permissions,
        policy_version=POLICY_VERSION,
        node_key=node_key,
        depth=depth,
        tenant_config=dict(tenant.settings or {}),
        agent_config={**(setting.config if setting else {}), **(extra_context or {})},
    )
    services = AgentServices(db, ctx, spec.allowed_tools, get_gateway(), spec.token_budget, model_override=setting.model_override if setting else None)

    started = time.perf_counter()
    try:
        agent = agent_cls()
        result = agent.run(ctx, payload, services)
        result = _post_validate(agent_cls, result)
        result.warnings.extend(services.budget.warnings)
    except OpsPilotError as exc:
        _finalize_failure(db, agent_run, exc.to_dict(), started, services)
        raise
    except ValidationError as exc:
        err = {"code": "agent_output_invalid", "message": "Agent produced invalid output", "details": {"errors": exc.errors()[:8]}}
        _finalize_failure(db, agent_run, err, started, services)
        raise ValidationFailed("Agent produced invalid output", details=err["details"]) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("agent.exception", agent=agent_key)
        _finalize_failure(db, agent_run, {"code": "agent_exception", "message": str(exc)[:500]}, started, services)
        raise OpsPilotError(f"Agent '{agent_key}' crashed: {exc}") from exc

    outcomes: list[ActionOutcome] = []
    if execute_actions and result.proposed_actions:
        action_service = ActionService(db, tenant, ctx, spec, agent_run_id=str(agent_run.id))
        outcomes = action_service.process(
            result.proposed_actions,
            evidence=result.evidence_refs,
            context={"summary": result.summary, "correlation_id": correlation_id, "workflow_run_id": workflow_run_id, "input_preview": _preview(agent_run.input)},
            node_key=node_key,
        )

    status = result.status
    if any(o.outcome == "approval_pending" for o in outcomes):
        status = "needs_approval"
    if any(o.outcome in {"failed", "unknown"} for o in outcomes) and status == "completed":
        result.warnings.append("One or more proposed actions did not complete; see action outcomes")

    latency_ms = int((time.perf_counter() - started) * 1000)
    usage = services.budget.as_dict()
    agent_run.status = status
    agent_run.output = result.data
    agent_run.evidence_refs = result.evidence_refs
    agent_run.missing_information = result.missing_information
    agent_run.proposed_actions = [a.model_dump(mode="json") for a in result.proposed_actions]
    agent_run.warnings = result.warnings
    agent_run.model = ",".join(usage["models"]) if usage["models"] else None
    agent_run.prompt_tokens = usage["prompt_tokens"]
    agent_run.completion_tokens = usage["completion_tokens"]
    agent_run.cost_usd = usage["cost_usd"]
    agent_run.latency_ms = latency_ms
    agent_run.finished_at = datetime.now(UTC)
    agent_run.output = {**result.data, "_summary": result.summary, "_actions": [o.model_dump(mode="json", exclude={"decision"}) for o in outcomes], "_tool_modes": sorted(services.tools.modes_used), "_confidence": result.confidence}
    db.flush()

    if usage["prompt_tokens"] or usage["completion_tokens"]:
        record_usage(db, tenant_id=tenant.id, kind="llm_tokens", quantity=usage["prompt_tokens"] + usage["completion_tokens"], cost_usd=usage["cost_usd"], agent_key=agent_key, run_id=workflow_run_id, model=agent_run.model, meta={"calls": usage["calls"]})
    record_usage(db, tenant_id=tenant.id, kind="agent_run", quantity=1, agent_key=agent_key, run_id=workflow_run_id, meta={"status": status, "latency_ms": latency_ms})
    record_audit(
        db, tenant_id=tenant.id, action="agent.run", resource_type="agent_run", resource_id=str(agent_run.id), actor_id=actor_id, actor_type="agent" if actor_id == "system" else "user",
        details={"agent": agent_key, "status": status, "actions": [o.outcome for o in outcomes], "latency_ms": latency_ms, "cost_usd": usage["cost_usd"], "tool_modes": sorted(services.tools.modes_used)},
        correlation_id=correlation_id,
    )
    db.commit()
    return AgentRunOutcome(
        agent_run_id=str(agent_run.id), agent_key=agent_key, status=status, result=result, actions=outcomes, latency_ms=latency_ms, usage=usage, tool_modes=sorted(services.tools.modes_used)
    )


def _post_validate(agent_cls: type[BaseAgent], result: AgentResult) -> AgentResult:
    """Validate the structured data against the declared output schema and sanity-check evidence."""
    validated = agent_cls.spec.output_model.model_validate(result.data)
    result.data = validated.model_dump(mode="json")
    known = set(result.evidence_refs)
    for action in result.proposed_actions:
        for ref in action.evidence_refs:
            if ref not in known:
                result.warnings.append(f"Action '{action.action_type}' cites evidence '{ref}' not present in result evidence")
    return result


def _finalize_failure(db: Session, agent_run: AgentRun, error: dict[str, Any], started: float, services: AgentServices) -> None:
    agent_run.status = "failed"
    agent_run.error = error
    agent_run.latency_ms = int((time.perf_counter() - started) * 1000)
    agent_run.finished_at = datetime.now(UTC)
    usage = services.budget.as_dict()
    agent_run.prompt_tokens = usage["prompt_tokens"]
    agent_run.completion_tokens = usage["completion_tokens"]
    agent_run.cost_usd = usage["cost_usd"]
    db.flush()
    db.commit()


def _preview(data: dict[str, Any], max_len: int = 600) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in data.items():
        s = v if isinstance(v, int | float | bool) or v is None else str(v)
        if isinstance(s, str) and len(s) > max_len:
            s = s[:max_len] + "…"
        out[k] = s
    return out
