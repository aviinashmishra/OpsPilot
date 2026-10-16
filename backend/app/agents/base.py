"""Shared agent execution contract.

Every agent:
* declares an AgentSpec (identity, schemas, allowed tools, policies, budgets),
* receives an AgentContext (who/where/why) and AgentServices (LLM gateway,
  scoped tool invoker, retrieval, clock),
* returns an AgentResult with structured data, evidence references, missing
  information, proposed actions and warnings.

Agents never execute side-effecting actions themselves. They *propose* actions;
the ActionService validates, authorises (policy engine + approvals) and executes
them through the tool registry.
"""

from __future__ import annotations

import abc
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

RiskLevel = Literal["low", "medium", "high", "critical"]
AgentStatus = Literal["completed", "needs_input", "needs_approval", "escalated", "failed"]
Department = Literal[
    "sales_revenue",
    "customer_support",
    "ecommerce",
    "operations",
    "finance_admin",
    "technology_product",
]

DEPARTMENT_LABELS: dict[str, str] = {
    "sales_revenue": "Sales & Revenue",
    "customer_support": "Customer Support",
    "ecommerce": "E-Commerce",
    "operations": "Operations & Management",
    "finance_admin": "Finance & Administration",
    "technology_product": "Technology & Product",
}


class AgentInput(BaseModel):
    """Base for agent input models: unknown fields are rejected, never silently ignored."""

    model_config = ConfigDict(extra="forbid")


class AgentContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    actor_id: str
    workflow_run_id: str | None = None
    agent_run_id: str | None = None
    correlation_id: str
    # Stable id of a unit of work that may be re-executed after a crash (bulk-run item); scopes action idempotency keys.
    idempotency_scope: str | None = None
    permissions: list[str] = Field(default_factory=list)
    policy_version: str = "v1"
    node_key: str | None = None
    depth: int = 0
    tenant_config: dict[str, Any] = Field(default_factory=dict)
    agent_config: dict[str, Any] = Field(default_factory=dict)
    now: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def has_permission(self, perm: str) -> bool:
        if "*" in self.permissions:
            return True
        if perm in self.permissions:
            return True
        scope = perm.split(":")[0]
        return f"{scope}:*" in self.permissions


class EvidenceRef(BaseModel):
    """A pointer to the source that supports a claim."""

    ref: str  # e.g. "transcript:line:12", "document:<id>#chunk:3", "crm:lead:L-100", "metric:orders_total"
    excerpt: str | None = None
    source_type: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class ProposedAction(BaseModel):
    """An action an agent would like the platform to execute on its behalf."""

    action_type: str  # e.g. "crm.update_lead", "email.send", "ticket.create"
    tool_key: str  # registered tool
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    risk_level: RiskLevel = "medium"
    evidence_refs: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None
    requires_approval: bool | None = None  # None => let the policy engine decide
    estimated_minutes_saved: float = 0.0


class AgentResult(BaseModel):
    status: AgentStatus
    data: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)
    estimated_minutes_saved: float = 0.0
    model: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)

    def add_evidence(self, ref: str, excerpt: str | None = None, source_type: str | None = None) -> str:
        if ref not in self.evidence_refs:
            self.evidence_refs.append(ref)
            self.evidence.append(EvidenceRef(ref=ref, excerpt=excerpt, source_type=source_type))
        return ref


class ApprovalRule(BaseModel):
    """Declarative approval requirement attached to an agent."""

    action_type: str  # glob-ish: "email.send" or "crm.*"
    condition: str | None = None  # human-readable; evaluated deterministically by the policy engine
    required_permission: str = "approvals:decide"
    always: bool = True


class AgentSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, protected_namespaces=())

    key: str
    name: str
    department: Department
    version: str = "1.0.0"
    description: str
    use_cases: list[str] = Field(default_factory=list)
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    allowed_tools: list[str] = Field(default_factory=list)
    permission_scopes: list[str] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    approval_rules: list[ApprovalRule] = Field(default_factory=list)
    timeout_seconds: int = 120
    token_budget: int = 8000
    risk_level: RiskLevel = "medium"
    model_tier: Literal["fast", "default"] = "default"
    evaluation_dataset: str | None = None
    baseline_minutes_saved: float = 10.0  # measured baseline for ROI (per successful run)

    def to_catalog_dict(self) -> dict[str, Any]:
        return {
            "agent_key": self.key,
            "name": self.name,
            "department": self.department,
            "department_label": DEPARTMENT_LABELS[self.department],
            "description": self.description,
            "use_cases": self.use_cases,
            "current_version": self.version,
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": self.output_model.model_json_schema(),
            "allowed_tools": self.allowed_tools,
            "permission_scopes": self.permission_scopes,
            "policies": self.policies,
            "approval_rules": [r.model_dump() for r in self.approval_rules],
            "timeout_seconds": self.timeout_seconds,
            "token_budget": self.token_budget,
            "risk_level": self.risk_level,
            "baseline_minutes_saved": self.baseline_minutes_saved,
        }


class BaseAgent(abc.ABC):
    """Base class every specialist agent extends."""

    spec: ClassVar[AgentSpec]

    @abc.abstractmethod
    def run(self, ctx: AgentContext, payload: BaseModel, services: AgentServices) -> AgentResult:  # noqa: F821
        """Execute the agent. `payload` is already validated against spec.input_model."""

    # Convenience helpers -------------------------------------------------
    @classmethod
    def validate_input(cls, raw: dict[str, Any]) -> BaseModel:
        return cls.spec.input_model.model_validate(raw)

    @classmethod
    def validate_output(cls, data: dict[str, Any]) -> BaseModel:
        return cls.spec.output_model.model_validate(data)


# Imported late to avoid a circular import in type checkers.
from app.agents.services import AgentServices  # noqa: E402,F401
