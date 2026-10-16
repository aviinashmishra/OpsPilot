"""audit chain sealing: content hash per event + sealed chain (seq, chain_hash)

Revision ID: c7d1e2f3a4b5
Revises: 88fedda6b7a9
Create Date: 2026-10-16

The previous chain read the latest event's hash inside each writer's transaction, so
concurrent writers (several workers) forked it. Events now carry a content hash and a
single sealer appends them to the chain (see app/services/audit.py).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "c7d1e2f3a4b5"
down_revision = "88fedda6b7a9"
branch_labels = None
depends_on = None

APP_ROLE = "opspilot_app"


def upgrade() -> None:
    with op.batch_alter_table("audit_events") as batch:
        batch.add_column(sa.Column("seq", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("chain_hash", sa.String(length=64), nullable=True))
        batch.create_unique_constraint("uq_audit_events_seq", ["tenant_id", "seq"])

    # Existing events: re-hash with the content-hash formula; the sealer chains them on its next run.
    from sqlalchemy.orm import Session

    from app.db.models import AuditEvent
    from app.services.audit import _event_hash

    bind = op.get_bind()
    with Session(bind=bind) as s:
        for evt in s.execute(sa.select(AuditEvent)).scalars().yield_per(1000):
            evt.hash = _event_hash(evt)
            evt.prev_hash = None
        s.flush()

    if bind.dialect.name == "postgresql":
        # The app role may only set the chain columns, never content (UPDATE on the table stays revoked).
        op.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN GRANT UPDATE (seq, prev_hash, chain_hash) ON audit_events TO {APP_ROLE}; END IF; END $$;")
        op.execute(
            """
            CREATE OR REPLACE FUNCTION opspilot_audit_seal_guard() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF OLD.seq IS NOT NULL THEN
                RAISE EXCEPTION 'audit event % is sealed and immutable', OLD.id;
              END IF;
              IF NEW.hash IS DISTINCT FROM OLD.hash OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                 OR NEW.created_at IS DISTINCT FROM OLD.created_at OR NEW.action IS DISTINCT FROM OLD.action
                 OR NEW.actor_id IS DISTINCT FROM OLD.actor_id OR NEW.actor_type IS DISTINCT FROM OLD.actor_type
                 OR NEW.resource_type IS DISTINCT FROM OLD.resource_type OR NEW.resource_id IS DISTINCT FROM OLD.resource_id
                 OR NEW.severity IS DISTINCT FROM OLD.severity OR NEW.details::text IS DISTINCT FROM OLD.details::text THEN
                RAISE EXCEPTION 'audit event content is immutable';
              END IF;
              RETURN NEW;
            END $$;
            """
        )
        op.execute("DROP TRIGGER IF EXISTS audit_events_seal_guard ON audit_events")
        op.execute("CREATE TRIGGER audit_events_seal_guard BEFORE UPDATE ON audit_events FOR EACH ROW EXECUTE FUNCTION opspilot_audit_seal_guard()")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_events_seal_guard ON audit_events")
        op.execute("DROP FUNCTION IF EXISTS opspilot_audit_seal_guard()")
        op.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN REVOKE UPDATE (seq, prev_hash, chain_hash) ON audit_events FROM {APP_ROLE}; END IF; END $$;")
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("uq_audit_events_seq", type_="unique")
        batch.drop_column("chain_hash")
        batch.drop_column("seq")
