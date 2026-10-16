"""Portable column types: UUID and JSON that work on PostgreSQL and SQLite."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CHAR, JSON, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


class GUID(TypeDecorator[uuid.UUID]):
    """Platform-independent UUID type (native uuid on PostgreSQL, CHAR(36) elsewhere)."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value) if isinstance(value, uuid.UUID) else str(uuid.UUID(str(value)))

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class JSONType(TypeDecorator[Any]):
    """JSONB on PostgreSQL, JSON elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class VectorType(TypeDecorator[Any]):
    """pgvector `vector` column on PostgreSQL (when enabled), JSON list elsewhere."""

    impl = Text
    cache_ok = True

    def __init__(self, dimensions: int = 1536) -> None:
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            from app.core.config import get_settings

            # Only when explicitly enabled: the `vector` extension must exist in the database
            # (decide before the first migration; the column type is fixed at creation).
            if get_settings().enable_pgvector:
                try:
                    from pgvector.sqlalchemy import Vector

                    return dialect.type_descriptor(Vector(self.dimensions))
                except Exception:  # pragma: no cover - pgvector package missing
                    pass
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return list(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return list(value)
