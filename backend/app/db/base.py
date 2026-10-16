"""Declarative base and shared mixins."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.db.types import GUID


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class TenantScopedMixin:
    """Every tenant-owned record carries a non-null tenant_id with an index.

    Application code must always filter by the authenticated tenant; on PostgreSQL
    the migration additionally installs row-level security policies keyed on the
    `app.current_tenant` session variable.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(GUID(), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    @declared_attr.directive
    def __table_args__(cls):  # noqa: N805
        return (Index(f"ix_{cls.__tablename__}_tenant_created", "tenant_id", "created_at"),)
