"""Resolve a tool key to its spec: built-in registry tools or tenant custom tools."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.tools.registry import ToolSpec, tool_registry


def resolve_tool_spec(db: Session, tenant_id: str | uuid.UUID, tool_key: str) -> ToolSpec | None:
    if tool_registry.has(tool_key):
        return tool_registry.get(tool_key)
    if tool_key.startswith("custom."):
        from app.tools.custom import load_tool, spec_for

        try:
            return spec_for(load_tool(db, tenant_id, tool_key.split(".", 1)[1]))
        except NotFound:
            return None
    return None
