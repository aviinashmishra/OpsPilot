"""Central workflow orchestrator.

A workflow is an explicit graph of typed nodes stored as JSON:

    {
      "start": "qualify",
      "nodes": {
        "qualify":  {"type": "agent", "agent": "lead_qualification",
                     "input": {"lead": "$.input.lead"}, "next": "is_qualified",
                     "on_failure": "end"},
        "is_qualified": {"type": "condition",
                     "when": {"path": "$.nodes.qualify.data.qualified", "equals": true},
                     "then": "outreach", "else": "end"},
        "outreach": {"type": "agent", "agent": "sales_development", "input": {...}, "next": "gate"},
        "gate":     {"type": "approval_gate", "next": "end"},
        "fanout":   {"type": "parallel", "branches": ["a", "b"], "next": "end"},
        "delegate": {"type": "workflow", "workflow": "other_key", "input": {...}, "next": "end"},
        "end":      {"type": "end"}
      }
    }

Guarantees
* Every node transition is checkpointed and committed before the next node runs,
  so a crashed worker resumes from the last completed node.
* Step count, delegation depth and run deadlines are bounded.
* Approval gates pause the run (`waiting_approval`) and resume when every
  approval raised by the run has been decided.
* Transient failures retry with backoff (bounded); terminal failures open an
  incident and a dead-letter entry.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.runner import run_agent
from app.core.config import get_settings
from app.core.errors import (
    AgentDisabled,
    Conflict,
    LLMError,
    NotFound,
    OpsPilotError,
    QuotaExceeded,
    TransientIntegrationError,
    ValidationFailed,
    WorkflowError,
)
from app.core.logging import correlation_id_var, get_logger, tenant_id_var
from app.db.models import (
    Approval,
    DeadLetter,
    Incident,
    Tenant,
    WorkflowCheckpoint,
    WorkflowDefinition,
    WorkflowRun,
)
from app.db.session import session_scope
from app.services.audit import record_audit
from app.services.usage import enforce_workflow_quota, record_usage

log = get_logger("orchestrator")
MAX_DELEGATION_DEPTH = 3
MAX_RUN_ATTEMPTS = 3
TERMINAL = {"completed", "failed", "cancelled", "timed_out"}
SYSTEM_PERMISSIONS = [
    "crm:*", "email:*", "chat:*", "issues:*", "helpdesk:*", "commerce:*", "accounting:*", "whatsapp:*",
    "workspace:*", "monitoring:*", "procurement:*", "feedback:*", "metrics:*", "tasks:*", "documents:*",
    "incidents:*", "workflows:*",
]


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------


def load_definition(db: Session, tenant_id: uuid.UUID, key: str) -> WorkflowDefinition:
    rows = db.execute(
        select(WorkflowDefinition)
        .where(WorkflowDefinition.key == key, WorkflowDefinition.is_active.is_(True))
        .order_by(WorkflowDefinition.version.desc())
    ).scalars().all()
    tenant_specific = [r for r in rows if r.tenant_id == tenant_id]
    shared = [r for r in rows if r.tenant_id is None]
    chosen = (tenant_specific or shared or [None])[0]
    if chosen is None:
        raise NotFound(f"Workflow '{key}' not found")
    validate_graph(chosen.graph)
    return chosen


def validate_graph(graph: dict[str, Any]) -> None:
    if not isinstance(graph, dict) or "start" not in graph or "nodes" not in graph:
        raise ValidationFailed("Workflow graph requires 'start' and 'nodes'")
    nodes = graph["nodes"]
    if graph["start"] not in nodes:
        raise ValidationFailed("Workflow start node does not exist")
    for key, node in nodes.items():
        ntype = node.get("type")
        if ntype not in {"agent", "condition", "approval_gate", "parallel", "workflow", "end", "action"}:
            raise ValidationFailed(f"Node '{key}' has unknown type '{ntype}'")
        for ref in ("next", "then", "else", "on_failure", "on_needs_input"):
            target = node.get(ref)
            if target and target not in nodes:
                raise ValidationFailed(f"Node '{key}' references missing node '{target}'")
        if ntype == "parallel":
            for b in node.get("branches", []):
                if b not in nodes:
                    raise ValidationFailed(f"Parallel node '{key}' references missing branch '{b}'")


def validate_start_input(graph: dict[str, Any], input: dict[str, Any]) -> None:
    """Check the input against the first agent's schema before a run exists, so a bad payload
    is rejected up front (422) instead of creating a run that fails at its first node."""
    from pydantic import ValidationError

    from app.agents.registry import agent_registry

    node = graph["nodes"][graph["start"]]
    agent_key = node.get("agent", "")
    if node.get("type") != "agent" or not agent_registry.has(agent_key):
        return
    mapped = map_input(node.get("input", {}), {"input": input, "nodes": {}, "run": {}})
    try:
        agent_registry.get(agent_key).validate_input(mapped)
    except ValidationError as exc:
        raise ValidationFailed(f"Invalid input for agent '{agent_key}'", details={"errors": exc.errors(include_url=False)[:8]}) from exc


# ---------------------------------------------------------------------------
# Starting runs
# ---------------------------------------------------------------------------


def start_run(
    db: Session,
    *,
    tenant_id: str,
    workflow_key: str,
    input: dict[str, Any],
    actor_id: str,
    idempotency_key: str | None = None,
    trigger_event_id: str | None = None,
    correlation_id: str | None = None,
    parent_run_id: str | None = None,
    depth: int = 0,
    enqueue: bool = True,
    permissions: list[str] | None = None,
    validate_input: bool = False,
) -> WorkflowRun:
    tid = uuid.UUID(str(tenant_id))
    tenant = db.get(Tenant, tid)
    if tenant is None:
        raise NotFound("Tenant not found")
    if tenant.status != "active" or tenant.emergency_disabled:
        raise Conflict("Tenant is not active or is emergency-disabled")
    if depth > MAX_DELEGATION_DEPTH:
        raise WorkflowError("Delegation depth exceeded")
    enforce_workflow_quota(db, tenant)
    definition = load_definition(db, tid, workflow_key)
    if validate_input:
        validate_start_input(definition.graph, input)

    if idempotency_key:
        existing = db.execute(
            select(WorkflowRun).where(WorkflowRun.tenant_id == tid, WorkflowRun.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing:
            return existing

    cid = correlation_id or uuid.uuid4().hex
    run = WorkflowRun(
        tenant_id=tid,
        workflow_definition_id=definition.id,
        workflow_key=definition.key,
        workflow_version=definition.version,
        status="pending",
        trigger_event_id=uuid.UUID(trigger_event_id) if trigger_event_id else None,
        actor_id=actor_id,
        correlation_id=cid,
        idempotency_key=idempotency_key,
        input=input,
        state={"nodes": {}, "permissions": permissions or SYSTEM_PERMISSIONS, "graph_version": definition.version},
        current_node=definition.graph["start"],
        parent_run_id=uuid.UUID(parent_run_id) if parent_run_id else None,
        depth=depth,
        deadline_at=datetime.now(UTC) + timedelta(seconds=definition.timeout_seconds or get_settings().workflow_default_timeout_seconds),
    )
    db.add(run)
    db.flush()
    record_usage(db, tenant_id=tid, kind="workflow_run", quantity=1, run_id=run.id, meta={"workflow": workflow_key})
    record_audit(db, tenant_id=tid, action="workflow.started", resource_type="workflow_run", resource_id=str(run.id), actor_id=actor_id, actor_type="user" if actor_id != "system" else "system", details={"workflow": workflow_key, "depth": depth}, correlation_id=cid)
    db.commit()
    if enqueue:
        from app.workers.queue import enqueue_run

        enqueue_run(str(run.id))
    return run


# ---------------------------------------------------------------------------
# Path resolution for input mapping
# ---------------------------------------------------------------------------


def resolve_path(path: str, scope: dict[str, Any]) -> Any:
    if not path.startswith("$."):
        return path
    cur: Any = scope
    for part in path[2:].split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else None
        else:
            return None
        if cur is None:
            return None
    return cur


def map_input(mapping: Any, scope: dict[str, Any]) -> Any:
    """Resolve `$.path` references. Unresolved references are omitted from dict
    mappings so the agent's input defaults apply instead of receiving None."""
    if isinstance(mapping, str):
        return resolve_path(mapping, scope)
    if isinstance(mapping, dict):
        out = {}
        for k, v in mapping.items():
            resolved = map_input(v, scope)
            if resolved is None and isinstance(v, str) and v.startswith("$."):
                continue
            out[k] = resolved
        return out
    if isinstance(mapping, list):
        return [map_input(v, scope) for v in mapping]
    return mapping


def _evaluate_condition(cond: dict[str, Any], scope: dict[str, Any]) -> bool:
    value = resolve_path(str(cond.get("path", "")), scope)
    if "equals" in cond:
        return value == cond["equals"]
    if "not_equals" in cond:
        return value != cond["not_equals"]
    if "in" in cond:
        return value in cond["in"]
    if "gt" in cond:
        return isinstance(value, int | float) and value > cond["gt"]
    if "gte" in cond:
        return isinstance(value, int | float) and value >= cond["gte"]
    if "lt" in cond:
        return isinstance(value, int | float) and value < cond["lt"]
    if "truthy" in cond:
        return bool(value) == bool(cond["truthy"])
    if "non_empty" in cond:
        return bool(value) == bool(cond["non_empty"])
    return bool(value)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def execute_run(run_id: str, worker_id: str = "local") -> dict[str, Any]:
    """Execute (or resume) a workflow run until it completes, waits or fails."""
    with session_scope() as db:
        run = db.get(WorkflowRun, uuid.UUID(run_id))
        if run is None:
            raise NotFound("Workflow run not found")
        correlation_id_var.set(run.correlation_id)
        tenant_id_var.set(str(run.tenant_id))
        if run.status in TERMINAL:
            return {"status": run.status}
        if run.cancel_requested:
            _finish(db, run, "cancelled", error={"code": "workflow_cancelled", "message": "cancelled before start"})
            return {"status": run.status}
        tenant = db.get(Tenant, run.tenant_id)
        assert tenant is not None
        definition = db.get(WorkflowDefinition, run.workflow_definition_id) if run.workflow_definition_id else None
        if definition is None:
            definition = load_definition(db, run.tenant_id, run.workflow_key)
        graph = definition.graph
        nodes = graph["nodes"]

        lease_token = f"{worker_id}:{uuid.uuid4().hex[:10]}"
        if not _acquire_run_lease(db, run.id, lease_token):
            log.info("workflow.lease_busy", run_id=run_id, owner=run.lease_owner)
            return {"status": "locked", "run_id": run_id, "owner": run.lease_owner}
        try:
            return _execute_locked(db, run, tenant, graph, nodes, worker_id, lease_token)
        finally:
            _release_run_lease(db, run.id, lease_token)


RUN_LEASE_SECONDS = 300


def _acquire_run_lease(db: Session, run_id: uuid.UUID, token: str) -> bool:
    """Atomic compare-and-set: only one executor may hold a run at a time."""
    from sqlalchemy import or_, update

    now = datetime.now(UTC)
    res = db.execute(
        update(WorkflowRun).execution_options(synchronize_session=False)
        .where(WorkflowRun.id == run_id, or_(WorkflowRun.lease_owner.is_(None), WorkflowRun.lease_until.is_(None), WorkflowRun.lease_until < now))
        .values(lease_owner=token, lease_until=now + timedelta(seconds=RUN_LEASE_SECONDS))
    )
    db.commit()
    return (res.rowcount or 0) == 1


def _renew_run_lease(db: Session, run_id: uuid.UUID, token: str) -> None:
    from sqlalchemy import update

    db.execute(update(WorkflowRun).execution_options(synchronize_session=False).where(WorkflowRun.id == run_id, WorkflowRun.lease_owner == token).values(lease_until=datetime.now(UTC) + timedelta(seconds=RUN_LEASE_SECONDS)))


def _release_run_lease(db: Session, run_id: uuid.UUID, token: str) -> None:
    from sqlalchemy import update

    try:
        db.rollback()
        db.execute(update(WorkflowRun).execution_options(synchronize_session=False).where(WorkflowRun.id == run_id, WorkflowRun.lease_owner == token).values(lease_owner=None, lease_until=None))
        db.commit()
    except Exception:  # noqa: BLE001 - an expired lease is also safe
        log.exception("workflow.lease_release_failed", run_id=str(run_id))


def _execute_locked(db: Session, run: WorkflowRun, tenant: Tenant, graph: dict[str, Any], nodes: dict[str, Any], worker_id: str, lease_token: str) -> dict[str, Any]:
    db.refresh(run)
    if run.status in TERMINAL:
        return {"status": run.status, "run_id": str(run.id)}
    run.status = "running"
    run.worker_id = worker_id
    run.started_at = run.started_at or datetime.now(UTC)
    run.heartbeat_at = datetime.now(UTC)
    db.commit()

    settings = get_settings()
    node_key: str | None = run.current_node or graph["start"]
    while node_key:
        db.refresh(run)
        _renew_run_lease(db, run.id, lease_token)
        if run.cancel_requested:
            _finish(db, run, "cancelled", error={"code": "workflow_cancelled", "message": "cancelled by user"})
            break
        if run.deadline_at and _aware(run.deadline_at) < datetime.now(UTC):
            _finish(db, run, "timed_out", error={"code": "workflow_timeout", "message": "run exceeded its deadline"})
            _open_incident(db, run, "workflow_timeout", "Workflow exceeded its deadline")
            break
        if run.step_count >= settings.workflow_max_steps:
            _finish(db, run, "failed", error={"code": "workflow_step_limit", "message": f"exceeded {settings.workflow_max_steps} steps"})
            _open_incident(db, run, "workflow_failed", "Workflow exceeded its step limit")
            break

        node = nodes.get(node_key)
        if node is None:
            _finish(db, run, "failed", error={"code": "workflow_error", "message": f"missing node {node_key}"})
            break
        run.current_node = node_key
        run.step_count += 1
        run.heartbeat_at = datetime.now(UTC)
        seq = run.step_count
        _checkpoint(db, run, seq, node_key, node["type"], "started", {})
        db.commit()
        started = datetime.now(UTC)
        try:
            next_key, wait = _execute_node(db, tenant, run, node_key, node, nodes)
        except (TransientIntegrationError, LLMError) as exc:
            _handle_transient(db, run, node_key, exc)
            break
        except QuotaExceeded as exc:
            _finish(db, run, "failed", error=exc.to_dict())
            _open_incident(db, run, "quota_exceeded", exc.message, severity="high")
            break
        except (AgentDisabled, ValidationFailed, OpsPilotError) as exc:
            failure_target = node.get("on_failure")
            _checkpoint(db, run, seq, node_key, node["type"], "failed", {"error": exc.to_dict()}, started)
            run.state = _merge_node_state(run.state, node_key, {"status": "failed", "error": exc.to_dict()})
            if failure_target:
                run.current_node = failure_target
                db.commit()
                node_key = failure_target
                continue
            _finish(db, run, "failed", error=exc.to_dict())
            _open_incident(db, run, "workflow_failed", f"Node '{node_key}' failed: {exc.message}")
            break
        except Exception as exc:  # noqa: BLE001
            log.exception("workflow.node_crash", node=node_key)
            err = {"code": "internal_error", "message": str(exc)[:500]}
            _checkpoint(db, run, seq, node_key, node["type"], "failed", {"error": err}, started)
            _finish(db, run, "failed", error=err)
            _open_incident(db, run, "workflow_failed", f"Node '{node_key}' crashed")
            break

        _checkpoint(db, run, seq, node_key, node["type"], "completed", {"next": next_key, "wait": wait}, started)
        if wait:
            run.status = "waiting_approval"
            run.state = {**run.state, "resume_node": next_key, "waiting_since": datetime.now(UTC).isoformat()}
            run.current_node = node_key
            db.commit()
            break
        run.current_node = next_key
        db.commit()
        node_key = next_key
        if node_key is None:
            _finish(db, run, "completed")

    db.refresh(run)
    return {"status": run.status, "run_id": str(run.id)}


def _execute_node(db: Session, tenant: Tenant, run: WorkflowRun, node_key: str, node: dict[str, Any], nodes: dict[str, Any]) -> tuple[str | None, bool]:
    """Returns (next_node_key, wait_for_approval)."""
    ntype = node["type"]
    scope = _scope(run)

    if ntype == "end":
        run.output = map_input(node.get("output", {}), scope) if node.get("output") else _default_output(run)
        return None, False

    if ntype == "condition":
        ok = _evaluate_condition(node.get("when", {}), scope)
        run.state = _merge_node_state(run.state, node_key, {"status": "completed", "result": ok})
        return (node.get("then") if ok else node.get("else")), False

    if ntype == "approval_gate":
        pending = db.execute(
            select(Approval).where(Approval.run_id == run.id, Approval.status == "pending")
        ).scalars().all()
        if pending:
            run.state = _merge_node_state(run.state, node_key, {"status": "waiting", "pending": [str(p.id) for p in pending]})
            return node.get("next"), True
        decided = db.execute(select(Approval).where(Approval.run_id == run.id)).scalars().all()
        summary = {
            "status": "completed",
            "approved": sum(1 for a in decided if a.status in {"approved", "executed"}),
            "rejected": sum(1 for a in decided if a.status == "rejected"),
            "expired": sum(1 for a in decided if a.status == "expired"),
            "execution_failed": sum(1 for a in decided if a.status == "execution_failed"),
        }
        run.state = _merge_node_state(run.state, node_key, summary)
        if summary["rejected"] and node.get("on_rejected"):
            return node["on_rejected"], False
        return node.get("next"), False

    if ntype == "agent":
        agent_key = str(resolve_path(node["agent"], scope) if str(node["agent"]).startswith("$.") else node["agent"])
        outcome = run_agent(
            db,
            tenant=tenant,
            agent_key=agent_key,
            input=map_input(node.get("input", {}), scope) or {},
            actor_id=run.actor_id or "system",
            permissions=list(run.state.get("permissions", SYSTEM_PERMISSIONS)),
            correlation_id=run.correlation_id,
            workflow_run_id=str(run.id),
            node_key=node_key,
            depth=run.depth,
            execute_actions=node.get("execute_actions", True),
            extra_context=node.get("config"),
        )
        run.cost_usd = round(run.cost_usd + float(outcome.usage.get("cost_usd", 0.0)), 6)
        run.estimated_minutes_saved = round(run.estimated_minutes_saved + (outcome.result.estimated_minutes_saved if outcome.status in {"completed", "needs_approval"} else 0.0), 2)
        run.state = _merge_node_state(run.state, node_key, _agent_state(outcome))
        if outcome.status == "needs_input" and node.get("on_needs_input"):
            return node["on_needs_input"], False
        if outcome.status == "failed" and node.get("on_failure"):
            return node["on_failure"], False
        return node.get("next"), False

    if ntype == "parallel":
        branches: list[str] = node.get("branches", [])
        results = _run_parallel(run, branches, nodes)
        for bkey, state in results.items():
            run.state = _merge_node_state(run.state, bkey, state)
        run.state = _merge_node_state(run.state, node_key, {"status": "completed", "branches": branches})
        run.cost_usd = round(run.cost_usd + sum(float(s.get("usage", {}).get("cost_usd", 0.0)) for s in results.values()), 6)
        run.estimated_minutes_saved = round(run.estimated_minutes_saved + sum(float(s.get("estimated_minutes_saved", 0.0)) for s in results.values()), 2)
        return node.get("next"), False

    if ntype == "workflow":
        if run.depth >= MAX_DELEGATION_DEPTH:
            raise WorkflowError("Delegation depth exceeded")
        child = start_run(
            db,
            tenant_id=str(run.tenant_id),
            workflow_key=node["workflow"],
            input=map_input(node.get("input", {}), scope) or {},
            actor_id=run.actor_id or "system",
            correlation_id=run.correlation_id,
            parent_run_id=str(run.id),
            depth=run.depth + 1,
            enqueue=False,
            idempotency_key=f"{run.id}:{node_key}",
        )
        result = execute_run(str(child.id), worker_id=run.worker_id or "local")
        db.refresh(child)
        run.state = _merge_node_state(run.state, node_key, {"status": child.status, "child_run_id": str(child.id), "output": child.output, "result": result})
        run.cost_usd = round(run.cost_usd + child.cost_usd, 6)
        return node.get("next"), False

    if ntype == "action":
        # Deterministic platform action without an agent (e.g. notify owner).
        from pydantic import BaseModel

        from app.agents.base import AgentContext, AgentSpec, ProposedAction
        from app.services.actions import ActionService

        class _Any(BaseModel):
            pass

        spec = AgentSpec(key="workflow.action", name="Workflow action", department="operations", description="deterministic workflow action", input_model=_Any, output_model=_Any, allowed_tools=[node["tool"]])
        ctx = AgentContext(tenant_id=str(run.tenant_id), actor_id=run.actor_id or "system", workflow_run_id=str(run.id), correlation_id=run.correlation_id, permissions=list(run.state.get("permissions", SYSTEM_PERMISSIONS)), node_key=node_key, depth=run.depth)
        svc = ActionService(db, tenant, ctx, spec)
        action = ProposedAction(action_type=node.get("action_type", node["tool"]), tool_key=node["tool"], payload=map_input(node.get("payload", {}), scope) or {}, reason=node.get("reason", "workflow action"), risk_level=node.get("risk_level", "low"))
        outcomes = svc.process([action], context={"workflow": run.workflow_key, "node": node_key}, node_key=node_key)
        run.state = _merge_node_state(run.state, node_key, {"status": "completed", "actions": [o.model_dump(mode="json", exclude={"decision"}) for o in outcomes]})
        wait = any(o.outcome == "approval_pending" for o in outcomes)
        return node.get("next"), wait

    raise WorkflowError(f"Unsupported node type {ntype}")


def _run_parallel(run: WorkflowRun, branches: list[str], nodes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Run agent branches concurrently, each in its own DB session."""
    run_id = str(run.id)

    def _branch(bkey: str) -> tuple[str, dict[str, Any]]:
        node = nodes[bkey]
        with session_scope() as bdb:
            brun = bdb.get(WorkflowRun, uuid.UUID(run_id))
            tenant = bdb.get(Tenant, brun.tenant_id)
            assert brun is not None and tenant is not None
            if node["type"] != "agent":
                return bkey, {"status": "skipped", "reason": "only agent nodes can run in parallel branches"}
            try:
                outcome = run_agent(
                    bdb,
                    tenant=tenant,
                    agent_key=node["agent"],
                    input=map_input(node.get("input", {}), _scope(brun)) or {},
                    actor_id=brun.actor_id or "system",
                    permissions=list(brun.state.get("permissions", SYSTEM_PERMISSIONS)),
                    correlation_id=brun.correlation_id,
                    workflow_run_id=run_id,
                    node_key=bkey,
                    depth=brun.depth,
                    execute_actions=node.get("execute_actions", True),
                )
                return bkey, _agent_state(outcome)
            except OpsPilotError as exc:
                return bkey, {"status": "failed", "error": exc.to_dict()}

    with ThreadPoolExecutor(max_workers=min(4, max(1, len(branches)))) as pool:
        return dict(pool.map(_branch, branches))


# ---------------------------------------------------------------------------
# Resume / recovery / cancellation
# ---------------------------------------------------------------------------


def resume_after_approval(db: Session, *, run_id: str, approval: Approval) -> None:
    run = db.get(WorkflowRun, uuid.UUID(run_id))
    if run is None or run.status != "waiting_approval":
        return
    pending = db.execute(select(Approval).where(Approval.run_id == run.id, Approval.status == "pending")).scalars().first()
    if pending:
        return
    run.status = "pending"
    run.current_node = run.state.get("resume_node")
    # Time spent waiting for a human does not count against the run's deadline (approvals may
    # legitimately take hours; the deadline bounds execution, not review).
    waiting_since = run.state.get("waiting_since")
    if run.deadline_at and waiting_since:
        waited = datetime.now(UTC) - _aware(datetime.fromisoformat(waiting_since))
        if waited > timedelta(0):
            run.deadline_at = _aware(run.deadline_at) + waited
    if run.current_node is None:
        _finish(db, run, "completed")
        db.commit()
        return
    db.commit()
    from app.workers.queue import enqueue_run

    enqueue_run(str(run.id))


def request_cancel(db: Session, run: WorkflowRun, actor_id: str) -> WorkflowRun:
    if run.status in TERMINAL:
        raise Conflict(f"Run is already {run.status}")
    run.cancel_requested = True
    if run.status in {"pending", "waiting_approval", "waiting_input"}:
        _finish(db, run, "cancelled", error={"code": "workflow_cancelled", "message": f"cancelled by {actor_id}"})
        for ap in db.execute(select(Approval).where(Approval.run_id == run.id, Approval.status == "pending")).scalars().all():
            ap.status = "superseded"
    record_audit(db, tenant_id=run.tenant_id, action="workflow.cancel_requested", resource_type="workflow_run", resource_id=str(run.id), actor_id=actor_id, correlation_id=run.correlation_id)
    db.commit()
    return run


def recover_stale_runs(db: Session, stale_after_seconds: int | None = None) -> list[str]:
    """Re-enqueue runs whose worker stopped heartbeating (process crash/restart)."""
    threshold = datetime.now(UTC) - timedelta(seconds=stale_after_seconds or get_settings().workflow_heartbeat_stale_seconds)
    rows = db.execute(select(WorkflowRun).where(WorkflowRun.status.in_(["running", "pending"]))).scalars().all()
    recovered: list[str] = []
    from app.workers.queue import enqueue_run

    for run in rows:
        hb = run.heartbeat_at or run.created_at
        if _aware(hb) < threshold:
            if run.attempt >= MAX_RUN_ATTEMPTS:
                _finish(db, run, "failed", error={"code": "workflow_recovery_exhausted", "message": "too many recovery attempts"})
                _open_incident(db, run, "workflow_failed", "Run could not be recovered after worker restarts")
                continue
            run.attempt += 1
            run.status = "pending"
            run.heartbeat_at = datetime.now(UTC)
            record_audit(db, tenant_id=run.tenant_id, action="workflow.recovered", resource_type="workflow_run", resource_id=str(run.id), actor_type="system", details={"attempt": run.attempt, "node": run.current_node}, correlation_id=run.correlation_id)
            recovered.append(str(run.id))
    db.commit()
    for rid in recovered:
        enqueue_run(rid)
    return recovered


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _scope(run: WorkflowRun) -> dict[str, Any]:
    return {"input": run.input, "nodes": run.state.get("nodes", {}), "run": {"id": str(run.id), "tenant_id": str(run.tenant_id), "actor_id": run.actor_id, "correlation_id": run.correlation_id}}


def _merge_node_state(state: dict[str, Any], node_key: str, value: dict[str, Any]) -> dict[str, Any]:
    nodes = dict(state.get("nodes", {}))
    nodes[node_key] = value
    return {**state, "nodes": nodes}


def _agent_state(outcome: Any) -> dict[str, Any]:
    return {
        "status": outcome.status,
        "agent_key": outcome.agent_key,
        "agent_run_id": outcome.agent_run_id,
        "data": outcome.result.data,
        "summary": outcome.result.summary,
        "evidence_refs": outcome.result.evidence_refs,
        "missing_information": outcome.result.missing_information,
        "warnings": outcome.result.warnings,
        "actions": [a.model_dump(mode="json", exclude={"decision"}) for a in outcome.actions],
        "pending_approvals": outcome.pending_approval_ids,
        "usage": outcome.usage,
        "estimated_minutes_saved": outcome.result.estimated_minutes_saved,
        "tool_modes": outcome.tool_modes,
    }


def _default_output(run: WorkflowRun) -> dict[str, Any]:
    nodes = run.state.get("nodes", {})
    return {
        "summary": {k: v.get("summary") for k, v in nodes.items() if isinstance(v, dict) and v.get("summary")},
        "statuses": {k: v.get("status") for k, v in nodes.items() if isinstance(v, dict)},
        "actions": [a for v in nodes.values() if isinstance(v, dict) for a in v.get("actions", [])],
        "missing_information": sorted({m for v in nodes.values() if isinstance(v, dict) for m in v.get("missing_information", [])}),
        "warnings": sorted({w for v in nodes.values() if isinstance(v, dict) for w in v.get("warnings", [])}),
        "estimated_minutes_saved": run.estimated_minutes_saved,
        "cost_usd": run.cost_usd,
    }


def _checkpoint(db: Session, run: WorkflowRun, seq: int, node_key: str, node_type: str, status: str, detail: dict[str, Any], started: datetime | None = None) -> None:
    existing = db.execute(select(WorkflowCheckpoint).where(WorkflowCheckpoint.run_id == run.id, WorkflowCheckpoint.sequence == seq)).scalar_one_or_none()
    duration = int((datetime.now(UTC) - started).total_seconds() * 1000) if started else None
    if existing:
        existing.status = status
        existing.detail = detail
        existing.state = {"nodes": run.state.get("nodes", {})}
        existing.duration_ms = duration
    else:
        db.add(WorkflowCheckpoint(tenant_id=run.tenant_id, run_id=run.id, sequence=seq, node_key=node_key, node_type=node_type, status=status, state={"nodes": run.state.get("nodes", {})}, detail=detail, duration_ms=duration))
    db.flush()


def _finish(db: Session, run: WorkflowRun, status: str, error: dict[str, Any] | None = None) -> None:
    run.status = status
    run.finished_at = datetime.now(UTC)
    run.error = error
    if status == "completed" and not run.output:
        run.output = _default_output(run)
    record_audit(db, tenant_id=run.tenant_id, action=f"workflow.{status}", resource_type="workflow_run", resource_id=str(run.id), actor_type="system", details={"workflow": run.workflow_key, "steps": run.step_count, "cost_usd": run.cost_usd, "error": error}, severity="warning" if status in {"failed", "timed_out"} else "info", correlation_id=run.correlation_id)
    db.commit()


def _handle_transient(db: Session, run: WorkflowRun, node_key: str, exc: OpsPilotError) -> None:
    run.attempt += 1
    if run.attempt >= MAX_RUN_ATTEMPTS:
        _finish(db, run, "failed", error=exc.to_dict())
        db.add(DeadLetter(tenant_id=run.tenant_id, kind="workflow_run", reference_id=str(run.id), payload={"node": node_key, "workflow": run.workflow_key}, error=exc.to_dict(), attempts=run.attempt))
        _open_incident(db, run, "workflow_failed", f"Transient failures exhausted at node '{node_key}'")
        db.commit()
        return
    run.status = "pending"
    run.current_node = node_key
    run.error = {**exc.to_dict(), "retrying": True, "attempt": run.attempt}
    db.commit()
    from app.workers.queue import enqueue_run

    enqueue_run(str(run.id), delay_seconds=min(30, 2**run.attempt))


def _open_incident(db: Session, run: WorkflowRun, kind: str, title: str, severity: str = "medium") -> None:
    db.add(Incident(tenant_id=run.tenant_id, severity=severity, title=title[:300], source="orchestrator", kind=kind, details={"workflow": run.workflow_key, "node": run.current_node, "error": run.error}, run_id=run.id))
    db.flush()
