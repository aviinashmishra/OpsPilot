"""Append-only, hash-chained audit log.

Writing and chaining are separate so the log scales with concurrent workers:

* ``record_audit`` stores the event with a *content hash* over its own fields. No read of
  the previous event, so concurrent transactions never fork the chain or contend.
* ``seal_chain`` (one sealer per tenant at a time; maintenance runs it every minute and
  ``verify_chain`` runs it first) appends committed, unsealed events to the tenant's chain:
  ``seq`` (gap-free), ``prev_hash`` (previous event's chain hash) and
  ``chain_hash = sha256(prev_hash + hash)``.
* ``verify_chain`` recomputes every content hash (detects edited events) and every link,
  and checks ``seq`` is contiguous (detects deleted events).

On PostgreSQL the application role cannot UPDATE/DELETE audit rows except the three chain
columns, and a trigger refuses to re-seal a sealed event or change its content.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import correlation_id_var, get_logger, redact
from app.db.models import AuditEvent, Tenant

log = get_logger("audit")
SEAL_BATCH = 5000


def _ts(dt: datetime) -> str:
    return (dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)).isoformat(timespec="microseconds")


def content_hash(*, event_id: uuid.UUID | str, tenant_id: uuid.UUID | str, action: str, resource_type: str, resource_id: str | None, actor_id: str | None, actor_type: str, details: dict[str, Any], severity: str, created_at: datetime) -> str:
    body = json.dumps(
        {
            "id": str(event_id), "tenant_id": str(tenant_id), "action": action, "resource_type": resource_type, "resource_id": resource_id,
            "actor_id": actor_id, "actor_type": actor_type, "details": details, "severity": severity, "created_at": _ts(created_at),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _event_hash(evt: AuditEvent) -> str:
    return content_hash(
        event_id=evt.id, tenant_id=evt.tenant_id, action=evt.action, resource_type=evt.resource_type, resource_id=evt.resource_id,
        actor_id=evt.actor_id, actor_type=evt.actor_type, details=evt.details or {}, severity=evt.severity, created_at=evt.created_at,
    )


def _link(prev: str | None, own: str) -> str:
    return hashlib.sha256(f"{prev or ''}:{own}".encode()).hexdigest()


def record_audit(
    db: Session,
    *,
    tenant_id: str | uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    actor_id: str | None = None,
    actor_type: str = "user",
    details: dict[str, Any] | None = None,
    severity: str = "info",
    ip_address: str | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    tid = uuid.UUID(str(tenant_id))
    # Normalise to plain JSON once, so the stored value and the hashed value are identical.
    safe_details = json.loads(json.dumps(redact(details or {}), default=str))
    evt = AuditEvent(
        id=uuid.uuid4(),
        tenant_id=tid,
        created_at=datetime.now(UTC),
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else None,
        correlation_id=correlation_id or correlation_id_var.get(),
        details=safe_details,
        severity=severity,
        ip_address=ip_address,
    )
    evt.hash = _event_hash(evt)
    db.add(evt)
    db.flush()
    return evt


def seal_chain(db: Session, tenant_id: str | uuid.UUID) -> int:
    """Append committed, unsealed events of one tenant to its chain. Returns how many were sealed."""
    from app.db.session import set_tenant_context

    tid = uuid.UUID(str(tenant_id))
    set_tenant_context(db, str(tid))
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        # One sealer per tenant; released at commit. Writers never take this lock.
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"audit-seal:{tid}"})
    head = db.execute(select(AuditEvent.seq, AuditEvent.chain_hash).where(AuditEvent.tenant_id == tid, AuditEvent.seq.isnot(None)).order_by(AuditEvent.seq.desc()).limit(1)).first()
    seq, prev = (head[0], head[1]) if head else (0, None)
    pending = db.execute(
        select(AuditEvent).where(AuditEvent.tenant_id == tid, AuditEvent.seq.is_(None)).order_by(AuditEvent.created_at, AuditEvent.id).limit(SEAL_BATCH)
    ).scalars().all()
    for evt in pending:
        seq += 1
        evt.seq = seq
        evt.prev_hash = prev
        evt.chain_hash = prev = _link(prev, evt.hash)
    try:
        db.commit()
    except IntegrityError:  # another sealer won the race (SQLite has no advisory locks); it sealed these
        db.rollback()
        return 0
    return len(pending)


def seal_all(db: Session) -> int:
    total = 0
    for tid in db.execute(select(Tenant.id)).scalars().all():
        while (n := seal_chain(db, tid)) == SEAL_BATCH:
            total += n
        total += n
    return total


def verify_chain(db: Session, tenant_id: str | uuid.UUID, limit: int = 100_000) -> dict[str, Any]:
    """Seal what is pending, then recompute every content hash and chain link of the tenant."""
    tid = uuid.UUID(str(tenant_id))
    while seal_chain(db, tid) == SEAL_BATCH:
        pass
    rows = db.execute(select(AuditEvent).where(AuditEvent.tenant_id == tid, AuditEvent.seq.isnot(None)).order_by(AuditEvent.seq).limit(limit)).scalars().all()
    # Retention purges the oldest events, so the chain is verified from the oldest retained one
    # (its prev_hash is the anchor). Any gap after that point means events were deleted.
    first_seq = rows[0].seq if rows else 1
    prev: str | None = rows[0].prev_hash if rows else None
    for i, evt in enumerate(rows):
        if evt.seq != first_seq + i:
            return {"ok": False, "checked": i, "broken_at": str(evt.id), "reason": f"sequence gap: expected {first_seq + i}, found {evt.seq} (events deleted)"}
        if _event_hash(evt) != evt.hash:
            return {"ok": False, "checked": i, "broken_at": str(evt.id), "reason": "content hash mismatch (event modified)"}
        if evt.prev_hash != prev or evt.chain_hash != _link(prev, evt.hash):
            return {"ok": False, "checked": i, "broken_at": str(evt.id), "reason": "chain link mismatch"}
        prev = evt.chain_hash
    unsealed = db.execute(select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == tid, AuditEvent.seq.is_(None))).scalar_one()
    return {"ok": True, "checked": len(rows), "unsealed": unsealed, "from_seq": first_seq, "head": prev}
