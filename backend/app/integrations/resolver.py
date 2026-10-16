"""Resolve the adapter to use for a (tenant, provider family).

Rules:
* If the tenant has an Integration row for the family with mode="live",
  status="connected" and stored credentials, build the live adapter.
* Otherwise fall back to the sandbox (mock) adapter and report mode="mock".
* Never silently treat a mock as live.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import IntegrationNotConfigured
from app.core.security import decrypt_secret
from app.db.models import Integration
from app.integrations.base import BaseAdapter
from app.integrations.mock_adapters import MOCK_ADAPTERS, PROVIDER_FAMILIES


@dataclass
class ResolvedAdapter:
    adapter: BaseAdapter
    mode: str
    provider: str
    integration_id: uuid.UUID | None
    live_provider: str | None = None


def _load_live_adapter(family: str, live_provider: str, config: dict[str, Any], credentials: dict[str, Any]) -> BaseAdapter | None:
    from app.integrations import live  # noqa: WPS433 - lazy import keeps optional SDKs out of the hot path

    return live.build(family, live_provider, config, credentials)


class AdapterResolver:
    def __init__(self, db: Session, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))
        self._cache: dict[str, ResolvedAdapter] = {}

    def resolve(self, family: str) -> ResolvedAdapter:
        if family in self._cache:
            return self._cache[family]
        if family == "platform":
            from app.tools.platform import PlatformAdapter

            resolved = ResolvedAdapter(adapter=PlatformAdapter(self.db, str(self.tenant_id)), mode="platform", provider="platform", integration_id=None)
            self._cache[family] = resolved
            return resolved
        if family == "custom":
            from app.tools.custom import CustomToolAdapter

            resolved = ResolvedAdapter(adapter=CustomToolAdapter(self.db, str(self.tenant_id)), mode="live", provider="custom", integration_id=None)  # type: ignore[arg-type]
            self._cache[family] = resolved
            return resolved
        if family not in PROVIDER_FAMILIES:
            raise IntegrationNotConfigured(f"Unknown provider family '{family}'")

        row = self.db.execute(
            select(Integration).where(Integration.tenant_id == self.tenant_id, Integration.provider == family)
        ).scalars().first()

        if row and row.mode == "live" and row.status == "connected" and row.encrypted_credentials:
            try:
                creds = json.loads(decrypt_secret(row.encrypted_credentials))
            except Exception:
                creds = {}
            live_provider = str(row.config.get("live_provider") or (PROVIDER_FAMILIES[family]["live_providers"] or ["unknown"])[0])
            adapter = _load_live_adapter(family, live_provider, dict(row.config), creds) if creds else None
            if adapter is not None:
                resolved = ResolvedAdapter(adapter=adapter, mode="live", provider=family, integration_id=row.id, live_provider=live_provider)
                self._cache[family] = resolved
                return resolved

        mock_cls = MOCK_ADAPTERS[family]
        resolved = ResolvedAdapter(adapter=mock_cls(self.db, str(self.tenant_id)), mode="mock", provider=family, integration_id=row.id if row else None)
        self._cache[family] = resolved
        return resolved
