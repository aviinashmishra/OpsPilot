"""Sync code-defined agents and built-in workflows into the database catalog."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.registry import agent_registry
from app.core.security import canonical_hash
from app.db.models import AgentDefinition, AgentVersion, WorkflowDefinition
from app.orchestration.definitions import BUILTIN_WORKFLOWS


def sync_catalog(db: Session) -> dict[str, int]:
    agents = 0
    for spec in agent_registry.specs():
        data = spec.to_catalog_dict()
        row = db.execute(select(AgentDefinition).where(AgentDefinition.agent_key == spec.key)).scalar_one_or_none()
        fields = {
            "name": data["name"], "department": data["department"], "description": data["description"], "use_cases": data["use_cases"],
            "current_version": data["current_version"], "input_schema": data["input_schema"], "output_schema": data["output_schema"],
            "allowed_tools": data["allowed_tools"], "permission_scopes": data["permission_scopes"], "policies": data["policies"],
            "approval_rules": data["approval_rules"], "timeout_seconds": data["timeout_seconds"], "token_budget": data["token_budget"], "risk_level": data["risk_level"],
        }
        if row is None:
            row = AgentDefinition(agent_key=spec.key, **fields)
            db.add(row)
            db.flush()
        else:
            for k, v in fields.items():
                setattr(row, k, v)
        if not db.execute(select(AgentVersion).where(AgentVersion.agent_definition_id == row.id, AgentVersion.version == spec.version)).scalar_one_or_none():
            db.add(AgentVersion(agent_definition_id=row.id, version=spec.version, changelog="Initial release", config={"allowed_tools": spec.allowed_tools}, prompt_hash=canonical_hash(data)[:64]))
        agents += 1

    workflows = 0
    for wf in BUILTIN_WORKFLOWS:
        if wf["key"] == "single_agent":
            continue
        row = db.execute(select(WorkflowDefinition).where(WorkflowDefinition.tenant_id.is_(None), WorkflowDefinition.key == wf["key"], WorkflowDefinition.version == 1)).scalar_one_or_none()
        if row is None:
            db.add(WorkflowDefinition(tenant_id=None, key=wf["key"], name=wf["name"], description=wf["description"], version=1, graph=wf["graph"], trigger=wf["trigger"], timeout_seconds=wf["timeout_seconds"]))
        else:
            row.graph = wf["graph"]
            row.name = wf["name"]
            row.description = wf["description"]
            row.trigger = wf["trigger"]
            row.timeout_seconds = wf["timeout_seconds"]
        workflows += 1
    db.flush()
    return {"agents": agents, "workflows": workflows}
