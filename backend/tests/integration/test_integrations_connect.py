"""Connecting a real system: form metadata, credential handling and hybrid resolution."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.core.security import decrypt_secret
from app.db.models import Integration, Tenant
from app.integrations.hybrid import HybridAdapter
from app.integrations.resolver import AdapterResolver


def test_catalog_describes_the_connect_form(client, admin_headers):
    fams = {f["key"]: f for f in client.get("/api/v1/integrations/catalog", headers=admin_headers).json()["families"]}
    assert set(fams["email"]["live_supported"]) == {"smtp", "sendgrid"} and set(fams["chat"]["live_supported"]) == {"webhook", "slack"}
    smtp = fams["email"]["connection"]["smtp"]
    assert [f["key"] for f in smtp["fields"]][:2] == ["host", "port"] and any(f["key"] == "password" and f["secret"] for f in smtp["fields"])
    assert fams["accounting"]["live_supported"] == [] and fams["accounting"]["live_providers"] == []


def test_updating_one_secret_keeps_the_others(client, admin_headers, db):
    body = {"provider": "helpdesk", "name": "Zendesk", "mode": "live", "live_provider": "zendesk", "config": {"subdomain": "acme"}, "credentials": {"email": "agent@acme.test", "api_token": "first"}, "scopes": []}
    assert client.post("/api/v1/integrations", json=body, headers=admin_headers).status_code == 201
    assert client.post("/api/v1/integrations", json={**body, "credentials": {"api_token": "rotated"}}, headers=admin_headers).status_code == 201
    tenant = db.execute(select(Tenant).where(Tenant.slug == "acme-demo")).scalar_one()
    row = db.execute(select(Integration).where(Integration.tenant_id == tenant.id, Integration.provider == "helpdesk")).scalar_one()
    db.refresh(row)
    assert json.loads(decrypt_secret(row.encrypted_credentials)) == {"email": "agent@acme.test", "api_token": "rotated"}
    assert row.status == "pending_test"  # never "connected" before a real connection test

    # Connected live: the resolver hands out the hybrid adapter.
    row.status = "connected"
    db.commit()
    resolved = AdapterResolver(db, str(tenant.id)).resolve("helpdesk")
    assert resolved.mode == "live" and isinstance(resolved.adapter, HybridAdapter)
    assert resolved.adapter.source_of("get_policies") == "workspace" and resolved.adapter.source_of("update_ticket") == "live"
    client.post("/api/v1/integrations", json={"provider": "helpdesk", "name": "Helpdesk (sandbox)", "mode": "mock", "config": {}, "scopes": []}, headers=admin_headers)
