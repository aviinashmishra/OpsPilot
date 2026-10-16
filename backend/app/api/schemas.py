"""Request/response schemas for the v1 API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

T = TypeVar("T")
# Syntactic e-mail check only (RFC 5322 deliverability is the IdP's job); allows reserved TLDs like .test for demos.
EmailStr = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[A-Za-z0-9-]{2,}$")]


class _Base(BaseModel):
    model_config = ConfigDict(protected_namespaces=())


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# --- Auth ------------------------------------------------------------------
class LoginRequest(BaseModel):
    tenant: str = Field(description="Tenant slug")
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
    tenant: TenantOut


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    full_name: str
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    is_active: bool = True


class TenantOut(BaseModel):
    id: str
    slug: str
    name: str
    plan: str
    status: str
    emergency_disabled: bool
    retention_days: int
    settings: dict[str, Any] = Field(default_factory=dict)
    quotas: dict[str, Any] = Field(default_factory=dict)
    feature_flags: dict[str, Any] = Field(default_factory=dict)


# --- Events ----------------------------------------------------------------
class EventIn(BaseModel):
    source: str = Field(max_length=64)
    event_type: str = Field(max_length=120)
    external_id: str | None = Field(default=None, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)
    workflow_key: str | None = Field(default=None, description="Override the default routing")
    occurred_at: datetime | None = None


class EventOut(BaseModel):
    id: str
    status: str
    event_type: str
    source: str
    dedupe_key: str
    workflow_run_id: str | None = None
    duplicate: bool = False
    received_at: datetime


# --- Workflows ---------------------------------------------------------------
class WorkflowStartIn(BaseModel):
    workflow_key: str
    input: dict[str, Any] = Field(default_factory=dict)


class CheckpointOut(BaseModel):
    sequence: int
    node_key: str
    node_type: str
    status: str
    detail: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int | None = None
    created_at: datetime


class AgentRunOut(BaseModel):
    id: str
    agent_key: str
    agent_version: str
    node_key: str | None = None
    status: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    proposed_actions: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int | None = None
    error: dict[str, Any] | None = None
    started_at: datetime
    finished_at: datetime | None = None


class WorkflowRunOut(BaseModel):
    id: str
    workflow_key: str
    workflow_version: int
    status: str
    correlation_id: str
    actor_id: str | None = None
    current_node: str | None = None
    step_count: int
    attempt: int
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    cost_usd: float = 0.0
    estimated_minutes_saved: float = 0.0
    cancel_requested: bool = False
    parent_run_id: str | None = None
    depth: int = 0
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    deadline_at: datetime | None = None
    checkpoints: list[CheckpointOut] = Field(default_factory=list)
    agent_runs: list[AgentRunOut] = Field(default_factory=list)
    pending_approvals: list[str] = Field(default_factory=list)
    graph: dict[str, Any] | None = None


class WorkflowDefinitionOut(BaseModel):
    id: str
    key: str
    name: str
    description: str | None = None
    version: int
    graph: dict[str, Any]
    trigger: dict[str, Any]
    is_active: bool
    timeout_seconds: int
    scope: str  # platform|tenant


class WorkflowDefinitionIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]{3,80}$")
    name: str = Field(max_length=160)
    description: str | None = None
    graph: dict[str, Any]
    trigger: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=600, ge=30, le=86400)


# --- Agents ------------------------------------------------------------------
class AgentCatalogOut(_Base):
    agent_key: str
    name: str
    department: str
    department_label: str
    description: str
    use_cases: list[str]
    current_version: str
    allowed_tools: list[str]
    permission_scopes: list[str]
    policies: list[str]
    approval_rules: list[dict[str, Any]]
    timeout_seconds: int
    token_budget: int
    risk_level: str
    baseline_minutes_saved: float
    enabled: bool
    globally_enabled: bool
    tenant_config: dict[str, Any] = Field(default_factory=dict)
    model_override: str | None = None
    disabled_reason: str | None = None
    stats: dict[str, Any] = Field(default_factory=dict)


class AgentDetailOut(AgentCatalogOut):
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    recent_runs: list[AgentRunOut] = Field(default_factory=list)
    evaluation: dict[str, Any] | None = None
    example_input: dict[str, Any] | None = None  # a known-good input (first evaluation case) to pre-fill the playground


class AgentSettingIn(_Base):
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    model_override: str | None = None
    disabled_reason: str | None = None


class AgentRunIn(BaseModel):
    input: dict[str, Any]
    mode: Literal["direct", "workflow"] = "workflow"


class AgentRunDirectOut(BaseModel):
    agent_run_id: str
    status: str
    result: dict[str, Any]
    actions: list[dict[str, Any]]
    latency_ms: int
    usage: dict[str, Any]
    tool_modes: list[str]
    workflow_run_id: str | None = None


# --- Tasks -------------------------------------------------------------------
class TaskIn(BaseModel):
    title: str = Field(max_length=300)
    description: str | None = None
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    owner_user_id: str | None = None
    owner_name: str | None = None
    due_at: datetime | None = None
    labels: list[str] = Field(default_factory=list)


class TaskUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    description: str | None = None
    status: Literal["open", "in_progress", "blocked", "done", "cancelled"] | None = None
    priority: Literal["low", "medium", "high", "critical"] | None = None
    owner_user_id: str | None = None
    owner_name: str | None = None
    due_at: datetime | None = None
    labels: list[str] | None = None


class TaskOut(BaseModel):
    id: str
    title: str
    description: str | None = None
    status: str
    priority: str
    owner_user_id: str | None = None
    owner_name: str | None = None
    due_at: datetime | None = None
    sla_hours: int | None = None
    source: str
    source_run_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    escalation_level: int = 0
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    overdue: bool = False


# --- Approvals -----------------------------------------------------------------
class ApprovalOut(BaseModel):
    id: str
    run_id: str | None = None
    agent_run_id: str | None = None
    agent_key: str | None = None
    node_key: str | None = None
    action_type: str
    tool_key: str | None = None
    action_payload: dict[str, Any]
    payload_hash: str
    context: dict[str, Any]
    evidence: list[str]
    reason: str | None = None
    risk_level: str
    policy_id: str | None = None
    policy_version: str | None = None
    status: str
    requested_by: str | None = None
    required_permission: str
    reviewer_id: str | None = None
    reviewer_name: str | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    expires_at: datetime
    executed_at: datetime | None = None
    execution_result: dict[str, Any] | None = None
    created_at: datetime


class ApprovalDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=2000)
    payload_hash: str | None = Field(default=None, description="Optional: the hash the reviewer saw; mismatch rejects the decision")


# --- Integrations ---------------------------------------------------------------
class IntegrationIn(BaseModel):
    provider: str = Field(description="Provider family key, e.g. crm, email, slack")
    name: str = Field(max_length=120)
    mode: Literal["mock", "live"] = "mock"
    live_provider: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] | None = Field(default=None, description="Stored encrypted; never returned")
    webhook_secret: str | None = None
    scopes: list[str] = Field(default_factory=list)


class IntegrationOut(BaseModel):
    id: str
    provider: str
    provider_label: str
    name: str
    mode: str
    status: str
    live_provider: str | None = None
    config: dict[str, Any]
    scopes: list[str]
    has_credentials: bool
    has_webhook_secret: bool
    last_sync_at: datetime | None = None
    last_test_at: datetime | None = None
    last_test_ok: bool | None = None
    last_error: str | None = None
    health: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    created_at: datetime


class ConnectionTestOut(BaseModel):
    ok: bool
    mode: str
    provider: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


# --- Reports / usage / audit ------------------------------------------------------
class AuditEventOut(BaseModel):
    id: str
    created_at: datetime
    actor_id: str | None = None
    actor_type: str
    action: str
    resource_type: str
    resource_id: str | None = None
    correlation_id: str | None = None
    details: dict[str, Any]
    severity: str
    hash: str  # content hash of this event
    seq: int | None = None  # chain position; None until the sealer has appended it (≤ 1 min)
    prev_hash: str | None = None
    chain_hash: str | None = None


class IncidentOut(BaseModel):
    id: str
    severity: str
    title: str
    source: str
    kind: str
    status: str
    details: dict[str, Any]
    run_id: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class OverviewOut(BaseModel):
    active_agents: int
    total_agents: int
    workflows_executed: int
    workflows_succeeded: int
    workflows_failed: int
    workflows_running: int
    estimated_minutes_saved: float
    realized_savings_usd: float
    ai_cost_usd: float
    infra_cost_usd: float
    pending_approvals: int
    open_incidents: int
    recent_incidents: list[IncidentOut]
    recent_runs: list[WorkflowRunOut]
    daily_series: list[dict[str, Any]]
    department_breakdown: list[dict[str, Any]]
    integration_modes: dict[str, int]
    period: dict[str, Any]


# --- Admin -------------------------------------------------------------------------
class TenantIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9-]{3,64}$")
    name: str = Field(max_length=200)
    plan: str = "starter"
    admin_email: EmailStr
    admin_name: str
    admin_password: str | None = Field(default=None, min_length=12)


class TenantUpdateIn(BaseModel):
    name: str | None = None
    plan: str | None = None
    status: Literal["active", "suspended", "disabled"] | None = None
    settings: dict[str, Any] | None = None
    quotas: dict[str, Any] | None = None
    feature_flags: dict[str, Any] | None = None
    retention_days: int | None = Field(default=None, ge=7, le=3650)
    emergency_disabled: bool | None = None


class UserIn(BaseModel):
    email: EmailStr
    full_name: str = Field(max_length=200)
    password: str | None = Field(default=None, min_length=12)
    roles: list[str] = Field(default_factory=list)
    external_subject: str | None = None


class UserUpdateIn(BaseModel):
    full_name: str | None = None
    roles: list[str] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=12)


class RoleIn(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9_]{2,64}$")
    description: str | None = None
    permissions: list[str]


class RoleOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    permissions: list[str]
    is_system: bool
    user_count: int = 0


class ApiKeyIn(BaseModel):
    name: str
    scopes: list[str]
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyOut(BaseModel):
    id: str
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    plaintext: str | None = Field(default=None, description="Only returned once at creation")


# --- Documents ------------------------------------------------------------------
class DocumentOut(BaseModel):
    id: str
    name: str
    collection: str
    content_type: str
    size_bytes: int
    sha256: str | None = None
    classification: str
    scan_status: str
    scan_findings: list[dict[str, Any]] = Field(default_factory=list)
    chunk_count: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DocumentTextIn(BaseModel):
    name: str = Field(max_length=300)
    collection: str = Field(default="kb", max_length=64)
    text: str = Field(max_length=2_000_000)
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    meta: dict[str, Any] = Field(default_factory=dict)


# --- Evaluations ------------------------------------------------------------------
class EvaluationRunIn(BaseModel):
    agent_key: str
    dataset_name: str | None = None


class EvaluationResultOut(BaseModel):
    id: str
    agent_key: str
    agent_version: str
    model: str | None = None
    metrics: dict[str, Any]
    case_results: list[dict[str, Any]]
    passed: bool
    created_at: datetime


TokenResponse.model_rebuild()
