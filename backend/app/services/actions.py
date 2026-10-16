"""ActionService: validate, authorise and execute proposed actions.

Flow for each ProposedAction returned by an agent:
  1. policy engine decides allow / require_approval / deny
  2. allow  -> execute now through the tool registry (idempotent, verified)
     require_approval -> create an Approval bound to the exact payload hash
     deny   -> record and skip
Execution is crash-safe: the ToolExecution row is committed as `in_progress`
before the external call; if the process dies, the reconciler verifies the
external outcome before anything is retried.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentContext, AgentSpec, ProposedAction
from app.core.config import get_settings
from app.core.errors import OpsPilotError, RateLimited, TransientIntegrationError, ValidationFailed
from app.core.logging import get_logger
from app.core.security import canonical_hash
from app.db.models import Approval, DeadLetter, Tenant, ToolExecution
from app.integrations.resolver import AdapterResolver
from app.policy.engine import PolicyDecision, evaluate_action
from app.services.audit import record_audit
from app.services.usage import record_usage
from app.tools.registry import ToolSpec, tool_registry

log = get_logger("actions")
MAX_EXECUTION_ATTEMPTS = 3


class ActionOutcome(BaseModel):
    action_type: str
    tool_key: str
    outcome: str  # executed|approval_pending|denied|failed|duplicate|unknown
    decision: PolicyDecision | None = None
    tool_execution_id: str | None = None
    approval_id: str | None = None
    response: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    mode: str | None = None
    external_ref: str | None = None
    idempotency_key: str | None = None
    reason: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


def derive_idempotency_key(tenant_id: str, tool_key: str, payload: dict[str, Any], scope: str | None = None) -> str:
    base = {"t": tenant_id, "tool": tool_key, "p": {k: v for k, v in payload.items() if k != "idempotency_key"}}
    if scope:
        base["scope"] = scope
    return f"{tool_key}:{canonical_hash(base)[:32]}"


class ActionService:
    def __init__(self, db: Session, tenant: Tenant, ctx: AgentContext, agent_spec: AgentSpec, agent_run_id: str | None = None) -> None:
        self.db = db
        self.tenant = tenant
        self.ctx = ctx
        self.agent_spec = agent_spec
        self.agent_run_id = agent_run_id
        self.resolver = AdapterResolver(db, ctx.tenant_id)
        self._ordinal = 0

    # ------------------------------------------------------------------
    def process(self, actions: list[ProposedAction], *, evidence: list[str] | None = None, context: dict[str, Any] | None = None, node_key: str | None = None) -> list[ActionOutcome]:
        outcomes: list[ActionOutcome] = []
        for action in actions:
            outcomes.append(self.process_one(action, evidence=evidence or [], context=context or {}, node_key=node_key))
        return outcomes

    def process_one(self, action: ProposedAction, *, evidence: list[str], context: dict[str, Any], node_key: str | None = None) -> ActionOutcome:
        decision = evaluate_action(
            ctx=self.ctx,
            agent_spec=self.agent_spec,
            action=action,
            tenant_settings=self.tenant.settings,
            emergency_disabled=self.tenant.emergency_disabled,
            tool_spec=self._spec(action.tool_key),
        )
        if decision.outcome == "deny":
            record_audit(
                self.db, tenant_id=self.tenant.id, action="action.denied", resource_type="proposed_action", actor_id=self.ctx.actor_id,
                actor_type="agent", details={"tool": action.tool_key, "policy": decision.policy_id, "reason": decision.reason}, severity="warning",
                correlation_id=self.ctx.correlation_id,
            )
            return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="denied", decision=decision, reason=decision.reason)

        if decision.outcome == "require_approval":
            approval = self.create_approval(action, decision, evidence=evidence, context=context, node_key=node_key)
            return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="approval_pending", decision=decision, approval_id=str(approval.id), reason=decision.reason)

        return self.execute(action, decision=decision)

    # ------------------------------------------------------------------
    def create_approval(self, action: ProposedAction, decision: PolicyDecision, *, evidence: list[str], context: dict[str, Any], node_key: str | None) -> Approval:
        payload = self._clean_payload(action)
        ttl = timedelta(hours=int((self.tenant.settings.get("policies", {}) or {}).get("approval_ttl_hours", get_settings().approval_default_ttl_hours)))
        bound = {"tool_key": action.tool_key, "action_type": action.action_type, "payload": payload, "tenant_id": self.ctx.tenant_id, "agent_key": self.agent_spec.key}
        existing = self.db.execute(
            select(Approval).where(Approval.tenant_id == self.tenant.id, Approval.payload_hash == canonical_hash(bound), Approval.status == "pending")
        ).scalars().first()
        if existing:
            return existing
        approval = Approval(
            tenant_id=self.tenant.id,
            run_id=uuid.UUID(self.ctx.workflow_run_id) if self.ctx.workflow_run_id else None,
            agent_run_id=uuid.UUID(self.agent_run_id) if self.agent_run_id else None,
            node_key=node_key,
            agent_key=self.agent_spec.key,
            action_type=action.action_type,
            tool_key=action.tool_key,
            action_payload=payload,
            payload_hash=canonical_hash(bound),
            context={**context, "agent_reason": action.reason, "estimated_minutes_saved": action.estimated_minutes_saved},
            evidence=list(dict.fromkeys([*evidence, *action.evidence_refs])),
            reason=decision.reason,
            risk_level=decision.risk_level,
            policy_id=decision.policy_id,
            policy_version=decision.policy_version,
            status="pending",
            requested_by=self.ctx.actor_id,
            required_permission=decision.required_permission,
            expires_at=datetime.now(UTC) + ttl,
        )
        self.db.add(approval)
        self.db.flush()
        record_audit(
            self.db, tenant_id=self.tenant.id, action="approval.requested", resource_type="approval", resource_id=str(approval.id),
            actor_id=self.ctx.actor_id, actor_type="agent", details={"tool": action.tool_key, "policy": decision.policy_id, "risk": decision.risk_level},
            correlation_id=self.ctx.correlation_id,
        )
        return approval

    # ------------------------------------------------------------------
    def execute(self, action: ProposedAction, *, decision: PolicyDecision | None = None, approval: Approval | None = None, actor_id: str | None = None) -> ActionOutcome:
        spec = self._spec(action.tool_key)
        if spec is None:
            return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="failed", decision=decision, error={"code": "unknown_tool", "message": f"Unknown tool '{action.tool_key}'"}, reason="unknown tool")
        try:
            payload = self._clean_payload(action)
        except ValidationFailed as exc:
            return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="failed", decision=decision, error=exc.to_dict(), reason="invalid payload")

        if action.idempotency_key:
            idem = action.idempotency_key
        elif self.ctx.idempotency_scope:
            # Work item that may be re-run after a crash (e.g. a bulk-run item). A re-run sees the world the first
            # run changed and a model words things differently, so it may propose other payloads or even other
            # tools. Key the n-th side effect of the item, whatever it is: a re-run can never do more than the
            # first run already did, it only fills in what is missing.
            self._ordinal += 1
            idem = "item:" + canonical_hash({"t": self.ctx.tenant_id, "scope": self.ctx.idempotency_scope, "n": self._ordinal})[:40]
        else:
            idem = derive_idempotency_key(self.ctx.tenant_id, action.tool_key, payload, scope=self.ctx.workflow_run_id)
        payload["idempotency_key"] = idem

        # Duplicate protection: a prior successful execution with the same key wins.
        prior = self.db.execute(
            select(ToolExecution).where(ToolExecution.tenant_id == self.tenant.id, ToolExecution.idempotency_key == idem)
        ).scalars().first()
        if prior is not None:
            if prior.status in {"succeeded", "verified", "reconciled"}:
                return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="duplicate", decision=decision, tool_execution_id=str(prior.id), response=prior.response, mode=prior.mode, external_ref=prior.external_ref, idempotency_key=idem, reason="identical action already executed")
            if prior.status == "unknown":
                reconciled = self.reconcile(prior)
                if reconciled.status in {"verified", "reconciled"}:
                    return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="duplicate", decision=decision, tool_execution_id=str(prior.id), response=prior.response, mode=prior.mode, external_ref=prior.external_ref, idempotency_key=idem, reason="unknown outcome reconciled as executed")
                if reconciled.status == "unknown":
                    return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="unknown", decision=decision, tool_execution_id=str(prior.id), idempotency_key=idem, reason="outcome still unverifiable; not retrying a non-idempotent action", mode=prior.mode)
            if prior.status == "in_progress" and not spec.idempotent:
                # The process died between the "attempted" marker and the result: the call may or may not have
                # happened. Never repeat a non-idempotent call blindly - ask the provider first.
                prior.status = "unknown"
                prior.error = {"code": "interrupted", "message": "worker stopped during the call"}
                reconciled = self.reconcile(prior)
                if reconciled.status in {"verified", "reconciled"}:
                    return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="duplicate", decision=decision, tool_execution_id=str(prior.id), response=prior.response, mode=prior.mode, external_ref=prior.external_ref, idempotency_key=idem, reason="interrupted call verified as executed")
                if reconciled.status == "unknown":
                    return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="unknown", decision=decision, tool_execution_id=str(prior.id), idempotency_key=idem, reason="interrupted call unverifiable; not retrying a non-idempotent action", mode=prior.mode)
            if prior.attempt >= MAX_EXECUTION_ATTEMPTS:
                return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="failed", decision=decision, tool_execution_id=str(prior.id), error=prior.error, idempotency_key=idem, reason="max attempts reached")
            rec = prior
            rec.attempt += 1
        else:
            resolved = self.resolver.resolve(spec.provider)
            rec = ToolExecution(
                tenant_id=self.tenant.id,
                run_id=uuid.UUID(self.ctx.workflow_run_id) if self.ctx.workflow_run_id else None,
                agent_run_id=uuid.UUID(self.agent_run_id) if self.agent_run_id else None,
                approval_id=approval.id if approval else None,
                integration_id=resolved.integration_id,
                tool_key=action.tool_key,
                provider=spec.provider,
                mode=resolved.mode,
                side_effect=spec.side_effect,
                idempotency_key=idem,
                request=payload,
                status="pending",
                attempt=1,
                actor_id=actor_id or self.ctx.actor_id,
                correlation_id=self.ctx.correlation_id,
            )
            self.db.add(rec)

        resolved = self.resolver.resolve(spec.provider)
        rec.status = "in_progress"
        rec.started_at = datetime.now(UTC)
        self.db.flush()
        self.db.commit()  # durable "attempted" marker before the external call

        started = time.perf_counter()
        try:
            method = getattr(resolved.adapter, spec.method)
            call_payload = dict(payload)
            if spec.provider == "platform":
                call_payload.setdefault("source_run_id", self.ctx.workflow_run_id)
                call_payload.setdefault("created_by", actor_id or self.ctx.actor_id)
                call_payload.setdefault("run_id", self.ctx.workflow_run_id)
                call_payload.setdefault("parent_run_id", self.ctx.workflow_run_id)
                call_payload.setdefault("depth", self.ctx.depth)
                call_payload.setdefault("actor_id", actor_id or self.ctx.actor_id)
            response = method(**call_payload)
            if not isinstance(response, dict):
                response = {"result": response}
            rec.response = response
            rec.external_ref = str(response.get(spec.external_ref_field)) if spec.external_ref_field and response.get(spec.external_ref_field) is not None else None
            rec.status = "succeeded"
            rec.finished_at = datetime.now(UTC)
            self.db.flush()
            record_usage(self.db, tenant_id=self.tenant.id, kind="tool_call", quantity=1, agent_key=self.agent_spec.key, run_id=self.ctx.workflow_run_id, meta={"tool": action.tool_key, "mode": resolved.mode})
            record_audit(
                self.db, tenant_id=self.tenant.id, action="action.executed", resource_type="tool_execution", resource_id=str(rec.id),
                actor_id=actor_id or self.ctx.actor_id, actor_type="agent" if not approval else "user",
                details={"tool": action.tool_key, "mode": resolved.mode, "external_ref": rec.external_ref, "duplicate_suppressed": response.get("duplicate_suppressed", False), "approval_id": str(approval.id) if approval else None, "latency_ms": int((time.perf_counter() - started) * 1000)},
                correlation_id=self.ctx.correlation_id,
            )
            self.db.commit()
            return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="executed", decision=decision, tool_execution_id=str(rec.id), response=response, mode=resolved.mode, external_ref=rec.external_ref, idempotency_key=idem, reason="executed")
        except (TransientIntegrationError, RateLimited) as exc:
            # Outcome unknown for non-idempotent operations: verify before any retry.
            rec.error = exc.to_dict()
            rec.finished_at = datetime.now(UTC)
            rec.status = "unknown" if not spec.idempotent else "failed"
            self.db.flush()
            self.db.commit()
            if rec.status == "unknown":
                reconciled = self.reconcile(rec)
                if reconciled.status in {"verified", "reconciled"}:
                    return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="executed", decision=decision, tool_execution_id=str(rec.id), response=rec.response, mode=resolved.mode, external_ref=rec.external_ref, idempotency_key=idem, reason="verified after transient failure")
                return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="unknown", decision=decision, tool_execution_id=str(rec.id), error=rec.error, mode=resolved.mode, idempotency_key=idem, reason="transient failure; outcome unverified")
            self._dead_letter_if_exhausted(rec)
            return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="failed", decision=decision, tool_execution_id=str(rec.id), error=rec.error, mode=resolved.mode, idempotency_key=idem, reason="transient failure")
        except OpsPilotError as exc:
            rec.error = exc.to_dict()
            rec.status = "failed"
            rec.finished_at = datetime.now(UTC)
            self.db.flush()
            self._dead_letter_if_exhausted(rec)
            self.db.commit()
            return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="failed", decision=decision, tool_execution_id=str(rec.id), error=rec.error, mode=resolved.mode, idempotency_key=idem, reason=exc.message)
        except Exception as exc:  # noqa: BLE001
            rec.error = {"code": "tool_exception", "message": str(exc)[:500]}
            rec.status = "failed"
            rec.finished_at = datetime.now(UTC)
            self.db.flush()
            self._dead_letter_if_exhausted(rec)
            self.db.commit()
            log.exception("action.exception", tool=action.tool_key)
            return ActionOutcome(action_type=action.action_type, tool_key=action.tool_key, outcome="failed", decision=decision, tool_execution_id=str(rec.id), error=rec.error, mode=resolved.mode, idempotency_key=idem, reason="unexpected error")

    # ------------------------------------------------------------------
    def reconcile(self, rec: ToolExecution) -> ToolExecution:
        """Ask the provider whether an action with unknown outcome actually happened."""
        spec = self._spec(rec.tool_key)
        if spec is None:
            return rec
        resolved = self.resolver.resolve(spec.provider)
        try:
            verification = resolved.adapter.verify_action(spec.method, rec.request, rec.external_ref or rec.idempotency_key)
        except Exception as exc:  # noqa: BLE001
            verification = None
            rec.verification = {"error": str(exc)[:300]}
        if verification is None:
            rec.verification = {**(rec.verification or {}), "verified": False, "reason": "provider cannot verify"}
            self.db.flush()
            self.db.commit()
            return rec
        rec.verification = verification.model_dump()
        rec.verified_at = datetime.now(UTC)
        if verification.verified and verification.exists:
            rec.status = "reconciled"
            rec.external_ref = verification.external_ref or rec.external_ref
        elif verification.verified and verification.exists is False:
            rec.status = "failed"  # safe to retry: provably did not happen
        self.db.flush()
        record_audit(self.db, tenant_id=self.tenant.id, action="action.reconciled", resource_type="tool_execution", resource_id=str(rec.id), actor_type="system", details={"status": rec.status, "verification": rec.verification}, correlation_id=self.ctx.correlation_id)
        self.db.commit()
        return rec

    def _dead_letter_if_exhausted(self, rec: ToolExecution) -> None:
        if rec.attempt >= MAX_EXECUTION_ATTEMPTS:
            rec.status = "dead_letter"
            self.db.add(DeadLetter(tenant_id=self.tenant.id, kind="tool_execution", reference_id=str(rec.id), payload={"tool": rec.tool_key, "request": rec.request}, error=rec.error, attempts=rec.attempt))
            self.db.flush()

    def _spec(self, tool_key: str) -> ToolSpec | None:
        from app.tools.resolve import resolve_tool_spec

        return resolve_tool_spec(self.db, self.tenant.id, tool_key)

    def _clean_payload(self, action: ProposedAction) -> dict[str, Any]:
        if action.tool_key.startswith("custom.") and not tool_registry.has(action.tool_key):
            from app.tools.custom import load_tool, validate_input

            tool = load_tool(self.db, self.tenant.id, action.tool_key.split(".", 1)[1])
            data = action.payload.get("input", action.payload) if isinstance(action.payload, dict) else {}
            data = {k: v for k, v in data.items() if k != "idempotency_key"}
            return {"tool": tool.name, "input": validate_input(tool.input_schema or {}, data)}
        try:
            return tool_registry.validate_payload(action.tool_key, action.payload)
        except ValidationError as exc:
            raise ValidationFailed(f"Invalid payload for '{action.tool_key}'", details={"errors": exc.errors()[:5]}) from exc
        except KeyError as exc:
            raise ValidationFailed(str(exc)) from exc


