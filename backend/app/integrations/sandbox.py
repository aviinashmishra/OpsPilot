"""Tenant-scoped sandbox store backing all mock adapters.

Synthetic business objects (leads, orders, invoices, products, tickets ...) live
in the `business_records` table. Mock adapters read/write here so every agent
and workflow can be exercised end-to-end without external credentials, and all
sandbox mutations are still tenant-isolated and auditable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BusinessRecord


class SandboxStore:
    def __init__(self, db: Session, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))

    # -- reads ---------------------------------------------------------------
    def list(self, record_type: str, *, limit: int = 500, **filters: Any) -> list[dict[str, Any]]:
        stmt = (
            select(BusinessRecord)
            .where(BusinessRecord.tenant_id == self.tenant_id, BusinessRecord.record_type == record_type)
            .order_by(BusinessRecord.created_at)
            .limit(limit)
        )
        rows = self.db.execute(stmt).scalars().all()
        out: list[dict[str, Any]] = []
        for r in rows:
            data = dict(r.data)
            data.setdefault("id", r.external_id)
            if all(self._matches(data, k, v) for k, v in filters.items() if v is not None):
                out.append(data)
        return out

    def get(self, record_type: str, external_id: str) -> dict[str, Any] | None:
        row = self._row(record_type, external_id)
        if row is None:
            return None
        data = dict(row.data)
        data.setdefault("id", row.external_id)
        return data

    def find_one(self, record_type: str, **filters: Any) -> dict[str, Any] | None:
        for rec in self.list(record_type, **filters):
            return rec
        return None

    # -- writes ---------------------------------------------------------------
    def upsert(self, record_type: str, external_id: str, data: dict[str, Any], status: str | None = None) -> dict[str, Any]:
        row = self._row(record_type, external_id)
        payload = dict(data)
        payload["id"] = external_id
        payload["updated_at"] = datetime.now(UTC).isoformat()
        if row is None:
            row = BusinessRecord(
                tenant_id=self.tenant_id, record_type=record_type, external_id=external_id, data=payload, status=status
            )
            self.db.add(row)
        else:
            merged = dict(row.data)
            merged.update(payload)
            row.data = merged
            if status is not None:
                row.status = status
            payload = merged
        self.db.flush()
        return payload

    def update(self, record_type: str, external_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        row = self._row(record_type, external_id)
        if row is None:
            return None
        merged = dict(row.data)
        merged.update(fields)
        merged["updated_at"] = datetime.now(UTC).isoformat()
        row.data = merged
        if "status" in fields:
            row.status = str(fields["status"])
        self.db.flush()
        merged.setdefault("id", external_id)
        return merged

    def append(self, record_type: str, data: dict[str, Any], prefix: str = "REC") -> dict[str, Any]:
        external_id = data.get("id") or f"{prefix}-{uuid.uuid4().hex[:8].upper()}"
        return self.upsert(record_type, external_id, data, status=data.get("status"))

    def delete(self, record_type: str, external_id: str) -> bool:
        row = self._row(record_type, external_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.flush()
        return True

    def count(self, record_type: str) -> int:
        return len(self.list(record_type, limit=100000))

    # -- internals ---------------------------------------------------------------
    def _row(self, record_type: str, external_id: str) -> BusinessRecord | None:
        stmt = select(BusinessRecord).where(
            BusinessRecord.tenant_id == self.tenant_id,
            BusinessRecord.record_type == record_type,
            BusinessRecord.external_id == str(external_id),
        )
        return self.db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def _matches(data: dict[str, Any], key: str, value: Any) -> bool:
        actual = data.get(key)
        if isinstance(value, list | tuple | set):
            return actual in value
        if isinstance(actual, str) and isinstance(value, str):
            return actual.lower() == value.lower()
        return actual == value
