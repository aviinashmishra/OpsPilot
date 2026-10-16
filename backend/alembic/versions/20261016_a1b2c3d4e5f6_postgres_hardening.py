"""PostgreSQL hardening: row-level security, append-only audit log, pgvector.

Revision ID: a1b2c3d4e5f6
Revises: e3ef553d9dba
Create Date: 2026-10-16

This migration is a no-op on SQLite. On PostgreSQL it:
* enables the `vector` extension when available (optional RAG),
* enables row-level security on every tenant-scoped table with a policy keyed
  on the `app.current_tenant` session variable (set per request/session by
  app.db.session.set_tenant_context). The migration/application owner role
  bypasses RLS; create a dedicated least-privilege role (e.g. `opspilot_app`)
  for the API and workers so the policies apply,
* revokes UPDATE/DELETE on audit_events from the application role so the
  audit trail is append-only at the database level.
"""

from __future__ import annotations

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "e3ef553d9dba"
branch_labels = None
depends_on = None

TENANT_TABLES = [
    "users", "roles", "api_keys", "integrations", "tenant_agent_settings", "business_events", "workflow_runs",
    "workflow_checkpoints", "agent_runs", "approvals", "tool_executions", "tasks", "documents", "document_chunks",
    "audit_events", "daily_metrics", "usage_records", "incidents", "dead_letters", "idempotency_records", "business_records",
]
APP_ROLE = "opspilot_app"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # Only if the server ships pgvector; plain PostgreSQL works too (embeddings then stored as JSONB).
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN CREATE EXTENSION IF NOT EXISTS vector; END IF; END $$;")
    op.execute(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN CREATE ROLE {APP_ROLE} NOLOGIN; END IF; END $$;")
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id::text = current_setting('app.current_tenant', true)) "
            f"WITH CHECK (tenant_id::text = current_setting('app.current_tenant', true))"
        )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON audit_events FROM {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON workflow_checkpoints FROM {APP_ROLE}")
    op.execute(f"GRANT UPDATE ON workflow_checkpoints TO {APP_ROLE}")  # status transitions only; deletes stay revoked


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
