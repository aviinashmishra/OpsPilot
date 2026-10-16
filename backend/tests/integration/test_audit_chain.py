"""Audit hash chain: concurrent writers never fork it, and edits or deletions are detected."""

import threading
import uuid

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

from app.db.models import AuditEvent, Tenant
from app.db.session import get_sessionmaker
from app.services.audit import record_audit, seal_chain, verify_chain


@pytest.fixture
def fresh_tenant(db):
    t = Tenant(slug=f"audit-{uuid.uuid4().hex[:8]}", name="Audit Co", plan="starter", settings={}, quotas={}, feature_flags={})
    db.add(t)
    db.commit()
    return t


def _write(tenant_id, n, tag):
    s = get_sessionmaker()()
    try:
        for i in range(n):
            record_audit(s, tenant_id=tenant_id, action=f"test.{tag}", resource_type="thing", resource_id=str(i), actor_id=tag, details={"i": i, "f": 0.1, "nested": {"b": [1, 2], "a": None}})
            s.commit()
    finally:
        s.close()


def test_concurrent_writers_produce_one_intact_chain(db, fresh_tenant):
    threads = [threading.Thread(target=_write, args=(fresh_tenant.id, 15, f"w{k}")) for k in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    out = verify_chain(db, fresh_tenant.id)
    assert out["ok"] is True and out["checked"] == 90 and out["unsealed"] == 0, out
    seqs = db.execute(select(AuditEvent.seq).where(AuditEvent.tenant_id == fresh_tenant.id).order_by(AuditEvent.seq)).scalars().all()
    assert seqs == list(range(1, 91))
    # Sealing is incremental: new events extend the existing chain.
    _write(fresh_tenant.id, 3, "late")
    assert verify_chain(db, fresh_tenant.id)["checked"] == 93


def _is_pg(db) -> bool:
    return db.bind.dialect.name == "postgresql"


def test_edited_event_is_detected(db, fresh_tenant):
    _write(fresh_tenant.id, 5, "e")
    assert verify_chain(db, fresh_tenant.id)["ok"] is True
    victim = db.execute(select(AuditEvent).where(AuditEvent.tenant_id == fresh_tenant.id, AuditEvent.seq == 3)).scalar_one()
    if _is_pg(db):
        # The database itself refuses to change a sealed event...
        with pytest.raises(DBAPIError, match="sealed"):
            db.execute(update(AuditEvent).where(AuditEvent.id == victim.id).values(details={"i": 999}))
            db.flush()
        db.rollback()
        db.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_seal_guard"))  # ...so a DBA-level attacker is simulated
    db.execute(update(AuditEvent).execution_options(synchronize_session=False).where(AuditEvent.id == victim.id).values(details={"i": 999}))
    db.commit()
    if _is_pg(db):
        db.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_seal_guard"))
        db.commit()
    db.expire_all()
    out = verify_chain(db, fresh_tenant.id)
    assert out["ok"] is False and out["broken_at"] == str(victim.id) and "content" in out["reason"]


def test_deleted_event_is_detected_but_retention_of_the_oldest_is_not_tampering(db, fresh_tenant):
    _write(fresh_tenant.id, 6, "d")
    assert verify_chain(db, fresh_tenant.id)["ok"] is True
    # Retention purges the oldest: the chain is verified from the oldest retained event.
    db.execute(delete(AuditEvent).where(AuditEvent.tenant_id == fresh_tenant.id, AuditEvent.seq <= 2))
    db.commit()
    kept = verify_chain(db, fresh_tenant.id)
    assert kept["ok"] is True and kept["checked"] == 4 and kept["from_seq"] == 3
    # Deleting from the middle breaks the sequence.
    db.execute(delete(AuditEvent).where(AuditEvent.tenant_id == fresh_tenant.id, AuditEvent.seq == 4))
    db.commit()
    out = verify_chain(db, fresh_tenant.id)
    assert out["ok"] is False and "gap" in out["reason"]


def test_seal_is_idempotent(db, fresh_tenant):
    _write(fresh_tenant.id, 4, "s")
    assert seal_chain(db, fresh_tenant.id) == 4
    assert seal_chain(db, fresh_tenant.id) == 0
