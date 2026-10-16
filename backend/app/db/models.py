"""SQLAlchemy ORM models for OpsPilot AI.

Conventions
-----------
* UUID primary keys, timezone-aware timestamps.
* Every tenant-owned table mixes in TenantScopedMixin (non-null tenant_id FK + index).
* Append-only tables (audit_events) are never updated in application code; the
  PostgreSQL migration also revokes UPDATE/DELETE from the application role.
* Secrets are only ever stored encrypted (integrations.encrypted_credentials) or hashed (api_keys.key_hash).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.db.types import GUID, JSONType, VectorType

# --------------------------------------------------------------------------
# Tenancy, identity and access
# --------------------------------------------------------------------------


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tenants"

    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    plan: Mapped[str] = mapped_column(String(32), default="starter", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)  # active|suspended|disabled
    settings: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    quotas: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    feature_flags: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=365, nullable=False)
    emergency_disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    users: Mapped[list[User]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        Index("ix_users_tenant_created", "tenant_id", "created_at"),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(200))
    external_subject: Mapped[str | None] = mapped_column(String(200), index=True)  # OIDC sub
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="users")
    roles: Mapped[list[Role]] = relationship(secondary="user_roles", back_populates="users")


class Role(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),
        Index("ix_roles_tenant_created", "tenant_id", "created_at"),
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    permissions: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    users: Mapped[list[User]] = relationship(secondary="user_roles", back_populates="roles")


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)


class ApiKey(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "api_keys"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scopes: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------------------------
# Integrations
# --------------------------------------------------------------------------


class Integration(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "integrations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "name", name="uq_integrations_tenant_provider_name"),
        Index("ix_integrations_tenant_created", "tenant_id", "created_at"),
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False)  # slack|jira|hubspot|...
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="mock", nullable=False)  # mock|live
    status: Mapped[str] = mapped_column(String(32), default="not_configured", nullable=False)
    config: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)  # non-secret settings
    encrypted_credentials: Mapped[str | None] = mapped_column(Text)
    scopes: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    webhook_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_error: Mapped[str | None] = mapped_column(Text)
    health: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)


# --------------------------------------------------------------------------
# Agent catalog
# --------------------------------------------------------------------------


class AgentDefinition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Global catalog of agents shipped with the platform (synced from the code registry)."""

    __tablename__ = "agent_definitions"

    agent_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    department: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    use_cases: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    current_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_schema: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    output_schema: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    allowed_tools: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    permission_scopes: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    policies: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    approval_rules: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    token_budget: Mapped[int] = mapped_column(Integer, default=8000, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    is_globally_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    versions: Mapped[list[AgentVersion]] = relationship(back_populates="definition", cascade="all, delete-orphan")


class AgentVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_definition_id", "version", name="uq_agent_versions_def_version"),)

    agent_definition_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("agent_definitions.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    changelog: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String(64))

    definition: Mapped[AgentDefinition] = relationship(back_populates="versions")


class TenantAgentSetting(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "tenant_agent_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_key", name="uq_tenant_agent_settings"),
        Index("ix_tenant_agent_settings_tenant_created", "tenant_id", "created_at"),
    )

    agent_key: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    model_override: Mapped[str | None] = mapped_column(String(80))
    disabled_reason: Mapped[str | None] = mapped_column(String(300))


# --------------------------------------------------------------------------
# Workflows and orchestration state
# --------------------------------------------------------------------------


class WorkflowDefinition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Workflow graphs. tenant_id NULL => platform template available to all tenants."""

    __tablename__ = "workflow_definitions"
    __table_args__ = (UniqueConstraint("tenant_id", "key", "version", name="uq_workflow_definitions_key_version"),)

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    graph: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    trigger: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=600, nullable=False)


class BusinessEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "business_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dedupe_key", name="uq_business_events_dedupe"),
        Index("ix_business_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_business_events_type", "tenant_id", "event_type"),
    )

    source: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(200))
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="received", nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("workflow_runs.id", ondelete="SET NULL"))
    error: Mapped[str | None] = mapped_column(Text)


class WorkflowRun(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_workflow_runs_idempotency"),
        Index("ix_workflow_runs_tenant_created", "tenant_id", "created_at"),
        Index("ix_workflow_runs_status", "tenant_id", "status"),
        Index("ix_workflow_runs_correlation", "correlation_id"),
    )

    workflow_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("workflow_definitions.id", ondelete="SET NULL")
    )
    workflow_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    workflow_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    # pending|running|waiting_approval|waiting_input|completed|failed|cancelled|timed_out
    trigger_event_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    actor_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    input: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    output: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    state: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    current_node: Mapped[str | None] = mapped_column(String(80))
    step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[dict | None] = mapped_column(JSONType())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(80))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Execution lease: at most one worker may execute a run at a time (horizontal scale safety).
    lease_owner: Mapped[str | None] = mapped_column(String(80))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    estimated_minutes_saved: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    checkpoints: Mapped[list[WorkflowCheckpoint]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="WorkflowCheckpoint.sequence"
    )
    agent_runs: Mapped[list[AgentRun]] = relationship(back_populates="run", cascade="all, delete-orphan")


class WorkflowCheckpoint(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "workflow_checkpoints"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_workflow_checkpoints_run_seq"),
        Index("ix_workflow_checkpoints_tenant_created", "tenant_id", "created_at"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    node_key: Mapped[str] = mapped_column(String(80), nullable=False)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    detail: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    run: Mapped[WorkflowRun] = relationship(back_populates="checkpoints")


class AgentRun(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_tenant_created", "tenant_id", "created_at"),
        Index("ix_agent_runs_agent", "tenant_id", "agent_key", "status"),
    )

    run_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    agent_key: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    node_key: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    input: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    output: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    missing_information: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    proposed_actions: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    warnings: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    model: Mapped[str | None] = mapped_column(String(80))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[dict | None] = mapped_column(JSONType())
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[WorkflowRun | None] = relationship(back_populates="agent_runs")


# --------------------------------------------------------------------------
# Approvals, tool executions, tasks
# --------------------------------------------------------------------------


class Approval(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_tenant_created", "tenant_id", "created_at"),
        Index("ix_approvals_status", "tenant_id", "status"),
    )

    run_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("agent_runs.id", ondelete="SET NULL"))
    node_key: Mapped[str | None] = mapped_column(String(80))
    agent_key: Mapped[str | None] = mapped_column(String(64))
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    tool_key: Mapped[str | None] = mapped_column(String(80))
    action_payload: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    context: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    policy_id: Mapped[str | None] = mapped_column(String(80))
    policy_version: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    # pending|approved|rejected|expired|executed|execution_failed|superseded
    requested_by: Mapped[str | None] = mapped_column(String(64))
    required_permission: Mapped[str] = mapped_column(String(80), default="approvals:decide", nullable=False)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tool_execution_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    execution_result: Mapped[dict | None] = mapped_column(JSONType())


class ToolExecution(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "tool_executions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tool_executions_idempotency"),
        Index("ix_tool_executions_tenant_created", "tenant_id", "created_at"),
        Index("ix_tool_executions_tool", "tenant_id", "tool_key", "status"),
    )

    run_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("workflow_runs.id", ondelete="SET NULL"))
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("agent_runs.id", ondelete="SET NULL"))
    approval_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("approvals.id", ondelete="SET NULL"))
    integration_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("integrations.id", ondelete="SET NULL"))
    tool_key: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16), default="mock", nullable=False)
    side_effect: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    request: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    response: Mapped[dict | None] = mapped_column(JSONType())
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    # pending|in_progress|succeeded|failed|unknown|verified|reconciled|dead_letter
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[dict | None] = mapped_column(JSONType())
    actor_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification: Mapped[dict | None] = mapped_column(JSONType())
    external_ref: Mapped[str | None] = mapped_column(String(200))


class Task(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_tenant_created", "tenant_id", "created_at"),
        Index("ix_tasks_status_due", "tenant_id", "status", "due_at"),
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)  # open|in_progress|blocked|done|cancelled
    priority: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id", ondelete="SET NULL"))
    owner_name: Mapped[str | None] = mapped_column(String(200))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_hours: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(64), default="manual", nullable=False)
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("workflow_runs.id", ondelete="SET NULL"))
    evidence_refs: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(200))
    labels: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    depends_on: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalation_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# --------------------------------------------------------------------------
# Documents and retrieval
# --------------------------------------------------------------------------


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_tenant_created", "tenant_id", "created_at"),
        Index("ix_documents_collection", "tenant_id", "collection"),
    )

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    collection: Mapped[str] = mapped_column(String(64), default="general", nullable=False)  # kb|sop|policy|...
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(400))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(String(32), default="internal", nullable=False)
    text_content: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(String(64))
    scan_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)  # pending|clean|flagged
    scan_findings: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    chunks: Mapped[list[DocumentChunk]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_doc_idx"),
        Index("ix_document_chunks_tenant_created", "tenant_id", "created_at"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str | None] = mapped_column(String(200))
    embedding: Mapped[list | None] = mapped_column(VectorType(1536))
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    document: Mapped[Document] = relationship(back_populates="chunks")


# --------------------------------------------------------------------------
# Audit, metrics, usage, incidents, dead letters, idempotency
# --------------------------------------------------------------------------


class AuditEvent(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    """Append-only, hash-chained audit trail."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_events_resource", "tenant_id", "resource_type", "resource_id"),
        Index("ix_audit_events_action", "tenant_id", "action"),
        UniqueConstraint("tenant_id", "seq", name="uq_audit_events_seq"),
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    actor_type: Mapped[str] = mapped_column(String(16), default="user", nullable=False)  # user|system|agent|api_key
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    details: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)  # content hash of this event
    # Chain position, assigned by the sealer (services.audit.seal_chain); NULL until sealed.
    seq: Mapped[int | None] = mapped_column(BigInteger)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    chain_hash: Mapped[str | None] = mapped_column(String(64))


class DailyMetric(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    __tablename__ = "daily_metrics"
    __table_args__ = (
        UniqueConstraint("tenant_id", "metric_date", "metric_key", "agent_key", name="uq_daily_metrics"),
        Index("ix_daily_metrics_tenant_created", "tenant_id", "created_at"),
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric_key: Mapped[str] = mapped_column(String(80), nullable=False)
    agent_key: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    dimensions: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)


class UsageRecord(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    __tablename__ = "usage_records"
    __table_args__ = (
        Index("ix_usage_records_tenant_created", "tenant_id", "created_at"),
        Index("ix_usage_records_period", "tenant_id", "period", "kind"),
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # llm_tokens|workflow_run|tool_call|agent_run
    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0, nullable=False)
    agent_key: Mapped[str | None] = mapped_column(String(64))
    run_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    model: Mapped[str | None] = mapped_column(String(80))
    meta: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)


class Incident(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_tenant_created", "tenant_id", "created_at"),
        Index("ix_incidents_status", "tenant_id", "status"),
    )

    severity: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)  # workflow_failed|cost_anomaly|integration_failure|policy_violation|release_anomaly
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    details: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeadLetter(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "dead_letters"

    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    error: Mapped[dict | None] = mapped_column(JSONType())
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)  # open|replayed|discarded


class IdempotencyRecord(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "scope", "key", name="uq_idempotency_records"),
        Index("ix_idempotency_records_tenant_created", "tenant_id", "created_at"),
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, default=200, nullable=False)


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


class EvaluationDataset(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "evaluation_datasets"
    __table_args__ = (UniqueConstraint("agent_key", "name", "version", name="uq_evaluation_datasets"),)

    agent_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    cases: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)


class EvaluationResult(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "evaluation_results"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("tenants.id", ondelete="SET NULL"))
    agent_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str | None] = mapped_column(String(80))
    metrics: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    case_results: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# --------------------------------------------------------------------------
# Durable job queue (horizontal scale without Redis)
# --------------------------------------------------------------------------


class Job(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A unit of background work claimed by worker processes with a renewable lease.

    Claiming uses `FOR UPDATE SKIP LOCKED` on PostgreSQL and an atomic conditional
    UPDATE elsewhere, so any number of workers can run concurrently; a worker that
    dies simply lets its lease expire and the job is re-queued by the reaper.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_jobs_dedupe"),
        Index("ix_jobs_claim", "status", "priority", "run_at"),
        Index("ix_jobs_tenant_status", "tenant_id", "status"),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)  # queued|running|done|failed|dead
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)  # lower runs first
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(80))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    last_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONType())


class WorkerHeartbeat(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "worker_heartbeats"

    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(120))
    pid: Mapped[int | None] = mapped_column(Integer)
    concurrency: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    active_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# --------------------------------------------------------------------------
# Bulk agent runs
# --------------------------------------------------------------------------


class AgentBatch(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "agent_batches"
    __table_args__ = (Index("ix_agent_batches_tenant_created", "tenant_id", "created_at"),)

    agent_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)  # running|completed|cancelled
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    needs_review: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    execute_actions: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class AgentBatchItem(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "agent_batch_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "item_index", name="uq_agent_batch_items_idx"),
        Index("ix_agent_batch_items_tenant_created", "tenant_id", "created_at"),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("agent_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    input: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)  # queued|running|completed|needs_review|failed
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    approval_ids: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)


# --------------------------------------------------------------------------
# Tenant-defined HTTP tools ("bring your own tool")
# --------------------------------------------------------------------------


class CustomTool(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "custom_tools"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_custom_tools_name"),
        Index("ix_custom_tools_tenant_created", "tenant_id", "created_at"),
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False)  # slug, exposed as custom.<name>
    description: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(String(8), default="GET", nullable=False)
    url_template: Mapped[str] = mapped_column(String(2000), nullable=False)
    headers: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)  # non-secret static headers
    auth_header_name: Mapped[str | None] = mapped_column(String(100))
    auth_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    input_schema: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    side_effect: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), default="low", nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64))
    last_called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    call_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# --------------------------------------------------------------------------
# Ops Copilot (model-driven tool use over agents and tools)
# --------------------------------------------------------------------------


class CopilotSession(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "copilot_sessions"
    __table_args__ = (Index("ix_copilot_sessions_tenant_created", "tenant_id", "created_at"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    messages: Mapped[list[CopilotMessage]] = relationship(back_populates="session", cascade="all, delete-orphan", order_by="CopilotMessage.sequence")


class CopilotMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "copilot_messages"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_copilot_messages_seq"),
        Index("ix_copilot_messages_tenant_created", "tenant_id", "created_at"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("copilot_sessions.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user|assistant
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="done", nullable=False)  # pending|running|done|failed
    llm_history: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)  # provider-format turns appended by this message
    mode: Mapped[str | None] = mapped_column(String(32))  # claude|offline_planner
    model: Mapped[str | None] = mapped_column(String(80))
    usage: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    session: Mapped[CopilotSession] = relationship(back_populates="messages")
    steps: Mapped[list[CopilotStep]] = relationship(back_populates="message", cascade="all, delete-orphan", order_by="CopilotStep.sequence")


class CopilotStep(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    __tablename__ = "copilot_steps"
    __table_args__ = (Index("ix_copilot_steps_tenant_created", "tenant_id", "created_at"),)

    message_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("copilot_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # agent|tool|custom|platform
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    input: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    output: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)  # running|ok|error|needs_approval
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    approval_ids: Mapped[list] = mapped_column(JSONType(), default=list, nullable=False)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID())

    message: Mapped[CopilotMessage] = relationship(back_populates="steps")


# --------------------------------------------------------------------------
# Synthetic business records (demo / sandbox data used by mock adapters)
# --------------------------------------------------------------------------


class BusinessRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin):
    """Generic tenant-scoped store for sandbox business objects (leads, orders,
    invoices, products, tickets, employees ...). Mock integration adapters read and
    write here so the whole platform is exercisable without external systems."""

    __tablename__ = "business_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "record_type", "external_id", name="uq_business_records_ext"),
        Index("ix_business_records_tenant_created", "tenant_id", "created_at"),
        Index("ix_business_records_type", "tenant_id", "record_type"),
    )

    record_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    data: Mapped[dict] = mapped_column(JSONType(), default=dict, nullable=False)
    status: Mapped[str | None] = mapped_column(String(32))
