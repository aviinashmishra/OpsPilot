"""Build the Copilot's tool catalog for one user in one tenant.

Every tool runs under the requesting user's permissions:

* ``agent__<key>``   - run a specialist agent (its proposed actions go through the
                       policy engine; consequential ones land in the approval center)
* ``<family>__<op>`` - read-only integration tools via the scoped ToolInvoker
* ``custom__<name>`` - tenant HTTP tools via ActionService (side effects need approval)
* ``ops__*``         - platform helpers (approvals, workflows, agent directory)
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentContext, ProposedAction
from app.agents.registry import agent_registry
from app.agents.runner import check_agent_enabled, run_agent
from app.agents.services import ToolInvoker
from app.copilot.spec import COPILOT_READ_TOOLS, COPILOT_SPEC
from app.db.models import Approval, CustomTool, Tenant, WorkflowDefinition, WorkflowRun
from app.integrations.mock_adapters import MOCK_ADAPTERS
from app.llm.tool_loop import LoopTool, ToolOutcome
from app.tools.registry import tool_registry

MAX_DATA_CHARS = 6000


def api_name(prefix: str, key: str) -> str:
    return f"{prefix}__{key.replace('.', '__')}"[:64]


def _has(perms: list[str], perm: str) -> bool:
    return "*" in perms or perm in perms or f"{perm.split(':')[0]}:*" in perms


def _ann_to_type(ann: Any) -> str:
    a = str(ann).lower()
    if "bool" in a:
        return "boolean"
    if "int" in a and "list" not in a:
        return "integer"
    if "float" in a:
        return "number"
    if "list" in a:
        return "array"
    if "dict" in a:
        return "object"
    return "string"


def schema_from_signature(fn: Any) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for name, p in inspect.signature(fn).parameters.items():
        if name in {"self", "idempotency_key"} or p.kind in {p.VAR_KEYWORD, p.VAR_POSITIONAL}:
            continue
        t = _ann_to_type(p.annotation)
        props[name] = {"type": t} if t != "array" else {"type": "array", "items": {}}
        if p.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


def _tool_schema(tool_key: str) -> dict[str, Any]:
    spec = tool_registry.get(tool_key)
    if spec.input_model is not None:
        return spec.input_model.model_json_schema()
    if spec.provider == "platform":
        from app.tools.platform import PlatformAdapter

        cls: Any = PlatformAdapter
    else:
        cls = MOCK_ADAPTERS[spec.provider]
    return schema_from_signature(getattr(cls, spec.method))


def _truncate(value: Any, limit: int = MAX_DATA_CHARS) -> Any:
    import json

    try:
        raw = json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)[:limit]
    if len(raw) <= limit:
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            piece = _truncate(v, max(200, limit // max(1, len(value))))
            out[k] = piece
        out["_truncated"] = True
        return out
    if isinstance(value, list):
        return [_truncate(v, max(200, limit // 10)) for v in value[:10]] + ([f"... {len(value) - 10} more"] if len(value) > 10 else [])
    return raw[:limit] + "...[truncated]"


class CopilotToolbox:
    def __init__(self, db: Session, tenant: Tenant, actor_id: str, permissions: list[str], correlation_id: str) -> None:
        self.db = db
        self.tenant = tenant
        self.actor_id = actor_id
        self.permissions = permissions
        self.correlation_id = correlation_id
        self.ctx = AgentContext(tenant_id=str(tenant.id), actor_id=actor_id, correlation_id=correlation_id, permissions=permissions, tenant_config=dict(tenant.settings or {}))

    # -- catalog -----------------------------------------------------------
    def build(self) -> list[LoopTool]:
        tools: list[LoopTool] = []
        tools.extend(self._platform_tools())
        if _has(self.permissions, "agents:run"):
            for agent_cls in agent_registry.all():
                spec = agent_cls.spec
                enabled, _ = check_agent_enabled(self.db, self.tenant, spec.key)
                if enabled:
                    tools.append(self._agent_tool(spec.key))
        invoker_ctx_tools = [k for k in COPILOT_READ_TOOLS if tool_registry.has(k) and _has(self.permissions, tool_registry.get(k).required_permission)]
        for key in invoker_ctx_tools:
            tools.append(self._read_tool(key))
        if _has(self.permissions, "tools:custom"):
            for ct in self.db.execute(select(CustomTool).where(CustomTool.tenant_id == self.tenant.id, CustomTool.enabled.is_(True)).order_by(CustomTool.name)).scalars().all():
                tools.append(self._custom_tool(ct))
        return tools

    # -- specialist agents --------------------------------------------------
    def _agent_tool(self, key: str) -> LoopTool:
        spec = agent_registry.get(key).spec

        def run(data: dict[str, Any]) -> ToolOutcome:
            out = run_agent(self.db, tenant=self.tenant, agent_key=key, input=data, actor_id=self.actor_id, permissions=self.permissions, correlation_id=self.correlation_id, extra_context={"invoked_by": "ops_copilot"})
            actions = [{"tool": a.tool_key, "outcome": a.outcome, "approval_id": a.approval_id, "reason": a.reason} for a in out.actions]
            approvals = [a.approval_id for a in out.actions if a.approval_id]
            res = out.result
            content = {
                "status": out.status,
                "summary": res.summary,
                "data": _truncate(res.data),
                "missing_information": res.missing_information,
                "warnings": res.warnings[:10],
                "actions": actions,
                "pending_approvals": approvals,
                "evidence_refs": res.evidence_refs[:20],
                "agent_run_id": out.agent_run_id,
                "note": "Consequential actions are never executed by you: they are policy-checked and, when required, wait in the approval center for a human.",
            }
            return ToolOutcome(content=content, summary=res.summary or out.status, status="needs_approval" if approvals else "ok", approval_ids=approvals, agent_run_id=out.agent_run_id)

        desc = f"{spec.name} ({spec.department.replace('_', ' ')}). {spec.description} Use cases: {', '.join(spec.use_cases[:4])}. Returns a structured result with evidence; any consequential action it proposes is policy-gated and may need human approval."
        return LoopTool(name=api_name("agent", key), description=desc, input_schema=spec.input_model.model_json_schema(), kind="agent", label=spec.name, run=run)

    # -- read-only integration tools -------------------------------------------
    def _read_tool(self, key: str) -> LoopTool:
        spec = tool_registry.get(key)
        invoker = ToolInvoker(self.db, self.ctx, COPILOT_READ_TOOLS)

        def run(data: dict[str, Any]) -> ToolOutcome:
            result = invoker.call(key, **data)
            count = result.get("count") if isinstance(result, dict) else None
            return ToolOutcome(content=_truncate(result), summary=f"{spec.name}: {count} item(s)" if count is not None else spec.name)

        return LoopTool(name=api_name(key.split(".")[0], key.split(".", 1)[1]), description=f"[read-only, {spec.provider}] {spec.description}", input_schema=_tool_schema(key), kind="tool", label=spec.name, run=run)

    # -- tenant custom tools ----------------------------------------------------
    def _custom_tool(self, ct: CustomTool) -> LoopTool:
        from app.services.actions import ActionService

        tool_key = f"custom.{ct.name}"

        def run(data: dict[str, Any]) -> ToolOutcome:
            svc = ActionService(self.db, self.tenant, self.ctx, COPILOT_SPEC)
            action = ProposedAction(action_type=tool_key, tool_key=tool_key, payload={"input": data}, reason=f"Ops Copilot requested {ct.name}", risk_level=ct.risk_level)  # type: ignore[arg-type]
            out = svc.process_one(action, evidence=[], context={"correlation_id": self.correlation_id, "summary": f"Copilot call to custom tool {ct.name}"})
            if out.outcome == "approval_pending":
                return ToolOutcome(content={"status": "pending_approval", "approval_id": out.approval_id, "reason": out.reason}, summary=f"{ct.name}: waiting for human approval", status="needs_approval", approval_ids=[out.approval_id] if out.approval_id else [])
            if out.outcome in {"executed", "duplicate"}:
                return ToolOutcome(content=_truncate(out.response), summary=f"{ct.name}: HTTP {(out.response or {}).get('status_code')}")
            return ToolOutcome(content={"error": out.reason, "details": out.error}, summary=f"{ct.name}: {out.outcome}", is_error=True, status="error")

        kind = "side-effecting, requires approval" if ct.side_effect else "read-only"
        schema = ct.input_schema or {"type": "object", "properties": {}}
        return LoopTool(name=api_name("custom", ct.name), description=f"[custom HTTP tool, {kind}] {ct.description}", input_schema=schema, kind="custom", label=ct.name, run=run)

    # -- platform helpers ----------------------------------------------------------
    def _platform_tools(self) -> list[LoopTool]:
        tid = self.tenant.id
        tools: list[LoopTool] = []

        def list_agents(_: dict[str, Any]) -> ToolOutcome:
            rows = [{"tool": api_name("agent", a.spec.key), "name": a.spec.name, "department": a.spec.department, "description": a.spec.description[:200]} for a in agent_registry.all()]
            return ToolOutcome(content={"agents": rows}, summary=f"{len(rows)} agents")

        tools.append(LoopTool(name="ops__list_agents", description="List the 25 specialist agents with what each one does.", input_schema={"type": "object", "properties": {}}, kind="platform", label="List agents", run=list_agents))

        if _has(self.permissions, "approvals:read"):
            def pending(data: dict[str, Any]) -> ToolOutcome:
                rows = self.db.execute(select(Approval).where(Approval.tenant_id == tid, Approval.status == "pending").order_by(Approval.created_at.desc()).limit(int(data.get("limit") or 20))).scalars().all()
                items = [{"id": str(a.id), "action_type": a.action_type, "tool": a.tool_key, "agent": a.agent_key, "risk": a.risk_level, "reason": a.reason, "created_at": a.created_at.isoformat()} for a in rows]
                return ToolOutcome(content={"pending": items, "note": "You cannot approve; only human reviewers can, in the approval center."}, summary=f"{len(items)} pending approval(s)")

            tools.append(LoopTool(name="ops__list_pending_approvals", description="List actions waiting for human approval (read-only; you cannot approve them).", input_schema={"type": "object", "properties": {"limit": {"type": "integer"}}}, kind="platform", label="Pending approvals", run=pending))

        if _has(self.permissions, "workflows:read"):
            def get_run(data: dict[str, Any]) -> ToolOutcome:
                run = self.db.get(WorkflowRun, uuid.UUID(str(data["run_id"])))
                if run is None or run.tenant_id != tid:
                    return ToolOutcome(content={"error": "run not found"}, summary="not found", is_error=True, status="error")
                nodes = {k: {"status": v.get("status"), "summary": v.get("summary")} for k, v in (run.state or {}).get("nodes", {}).items() if isinstance(v, dict)}
                return ToolOutcome(content={"id": str(run.id), "workflow": run.workflow_key, "status": run.status, "current_node": run.current_node, "nodes": nodes, "error": run.error}, summary=f"{run.workflow_key}: {run.status}", workflow_run_id=str(run.id))

            tools.append(LoopTool(name="ops__get_workflow_run", description="Get the status and per-step summaries of a workflow run.", input_schema={"type": "object", "properties": {"run_id": {"type": "string"}}, "required": ["run_id"]}, kind="platform", label="Workflow run", run=get_run))

            def list_defs(_: dict[str, Any]) -> ToolOutcome:
                rows = self.db.execute(select(WorkflowDefinition).where(WorkflowDefinition.is_active.is_(True), (WorkflowDefinition.tenant_id.is_(None)) | (WorkflowDefinition.tenant_id == tid))).scalars().all()
                items = [{"key": d.key, "name": d.name, "description": (d.description or "")[:200]} for d in rows if not d.key.startswith("single_agent__")]
                return ToolOutcome(content={"workflows": items}, summary=f"{len(items)} workflow(s)")

            tools.append(LoopTool(name="ops__list_workflows", description="List the multi-agent workflow templates that can be started.", input_schema={"type": "object", "properties": {}}, kind="platform", label="Workflow templates", run=list_defs))

        if _has(self.permissions, "workflows:write"):
            def start(data: dict[str, Any]) -> ToolOutcome:
                from app.orchestration.engine import start_run

                run = start_run(self.db, tenant_id=str(tid), workflow_key=str(data["workflow_key"]), input=dict(data.get("input") or {}), actor_id=self.actor_id, correlation_id=self.correlation_id, permissions=self.permissions, validate_input=True)
                self.db.refresh(run)
                return ToolOutcome(content={"run_id": str(run.id), "status": run.status, "note": "Durable run started; use ops__get_workflow_run to follow it."}, summary=f"started {run.workflow_key} ({run.status})", workflow_run_id=str(run.id))

            tools.append(LoopTool(name="ops__start_workflow", description="Start a durable multi-agent workflow (checkpointed, approval-gated). Use ops__list_workflows for keys and inputs.", input_schema={"type": "object", "properties": {"workflow_key": {"type": "string"}, "input": {"type": "object"}}, "required": ["workflow_key"]}, kind="platform", label="Start workflow", run=start))
        return tools
