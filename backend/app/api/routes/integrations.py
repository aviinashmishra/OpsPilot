"""Integration management. Credentials are write-only (stored Fernet-encrypted)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.schemas import ConnectionTestOut, IntegrationIn, IntegrationOut
from app.api.serializers import integration_out
from app.core.errors import NotFound, ValidationFailed
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models import Integration
from app.db.session import get_db
from app.integrations import live
from app.integrations.mock_adapters import MOCK_ADAPTERS, PROVIDER_FAMILIES
from app.services.audit import record_audit

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("", response_model=list[IntegrationOut], summary="List integrations (one row per provider family)")
def list_integrations(principal: Principal = Depends(require("integrations:read")), db: Session = Depends(get_db)) -> list[IntegrationOut]:
    rows = {r.provider: r for r in db.execute(select(Integration).where(Integration.tenant_id == principal.tenant.id)).scalars().all()}
    # Ensure every family is represented so the dashboard shows the full catalog.
    created = False
    for fam in PROVIDER_FAMILIES:
        if fam not in rows:
            r = Integration(tenant_id=principal.tenant.id, provider=fam, name=f"{PROVIDER_FAMILIES[fam]['label']} (sandbox)", mode="mock", status="sandbox", config={})
            db.add(r)
            rows[fam] = r
            created = True
    if created:
        db.commit()
    return [integration_out(rows[f]) for f in PROVIDER_FAMILIES]


@router.get("/catalog", summary="Provider families and supported live providers")
def catalog(principal: Principal = Depends(require("integrations:read"))) -> dict:
    return {
        "families": [
            {
                "key": k,
                **v,
                "live_supported": [p for (fam, p) in live.LIVE_ADAPTERS if fam == k],
                "required_credentials": {p: live.REQUIRED_CREDENTIALS.get((k, p), []) for (fam, p) in live.LIVE_ADAPTERS if fam == k},
                # What the Connect form asks for, per live provider (label, help link, fields).
                "connection": {p: live.CONNECTION_FIELDS[(k, p)] for (fam, p) in live.LIVE_ADAPTERS if fam == k and (k, p) in live.CONNECTION_FIELDS},
                "sandbox_capabilities": MOCK_ADAPTERS[k].capabilities if k in MOCK_ADAPTERS else [],
            }
            for k, v in PROVIDER_FAMILIES.items()
        ]
    }


@router.post("", response_model=IntegrationOut, status_code=201, summary="Create or update an integration")
def upsert_integration(body: IntegrationIn, principal: Principal = Depends(require("integrations:admin")), db: Session = Depends(get_db)) -> IntegrationOut:
    if body.provider not in PROVIDER_FAMILIES:
        raise ValidationFailed(f"Unknown provider family '{body.provider}'", details={"known": list(PROVIDER_FAMILIES)})
    if body.mode == "live":
        if not body.live_provider or (body.provider, body.live_provider) not in live.LIVE_ADAPTERS:
            raise ValidationFailed("Unsupported live provider for this family", details={"supported": [p for (f, p) in live.LIVE_ADAPTERS if f == body.provider]})
    row = db.execute(select(Integration).where(Integration.tenant_id == principal.tenant.id, Integration.provider == body.provider)).scalars().first()
    if row is None:
        row = Integration(tenant_id=principal.tenant.id, provider=body.provider, name=body.name)
        db.add(row)
    previous_provider = (row.config or {}).get("live_provider")
    row.name = body.name
    row.mode = body.mode
    row.config = {**body.config, **({"live_provider": body.live_provider} if body.live_provider else {})}
    row.scopes = body.scopes
    if body.credentials:
        # Merge: a form that re-enters one secret (e.g. a new password) keeps the others.
        stored: dict = {}
        if row.encrypted_credentials and previous_provider == body.live_provider:
            try:
                stored = json.loads(decrypt_secret(row.encrypted_credentials))
            except Exception:  # noqa: BLE001 - unreadable (rotated key): replace entirely
                stored = {}
        row.encrypted_credentials = encrypt_secret(json.dumps({**stored, **body.credentials}))
    if body.webhook_secret:
        row.webhook_secret_encrypted = encrypt_secret(body.webhook_secret)
    # A live integration is never "connected" until a real connection test succeeds.
    row.status = "sandbox" if body.mode == "mock" else "pending_test"
    row.last_test_ok = None
    db.flush()
    record_audit(db, tenant_id=principal.tenant.id, action="integration.configured", resource_type="integration", resource_id=str(row.id), actor_id=principal.actor_id, details={"provider": body.provider, "mode": body.mode, "live_provider": body.live_provider, "credentials_updated": bool(body.credentials)})
    db.commit()
    return integration_out(row)


@router.post("/{integration_id}/test", response_model=ConnectionTestOut, summary="Test the connection")
def test_integration(integration_id: str, principal: Principal = Depends(require("integrations:admin")), db: Session = Depends(get_db)) -> ConnectionTestOut:
    row = db.get(Integration, uuid.UUID(integration_id))
    if row is None or row.tenant_id != principal.tenant.id:
        raise NotFound("Integration not found")
    if row.mode == "mock":
        adapter = MOCK_ADAPTERS[row.provider](db, str(principal.tenant.id))
        result = adapter.test_connection()
        row.status = "sandbox"
    else:
        try:
            creds = json.loads(decrypt_secret(row.encrypted_credentials)) if row.encrypted_credentials else {}
            adapter = live.build(row.provider, str(row.config.get("live_provider")), dict(row.config), creds)
            if adapter is None:
                raise ValidationFailed("No live adapter for this provider")
            result = adapter.test_connection()
        except Exception as exc:  # noqa: BLE001
            from app.integrations.base import ConnectionTestResult

            result = ConnectionTestResult(ok=False, mode="live", provider=row.provider, message=str(exc)[:300])
        row.status = "connected" if result.ok else "error"
    row.last_test_at = datetime.now(UTC)
    row.last_test_ok = result.ok
    row.last_error = None if result.ok else result.message
    row.health = {"last_message": result.message, "checked_at": row.last_test_at.isoformat()}
    record_audit(db, tenant_id=principal.tenant.id, action="integration.tested", resource_type="integration", resource_id=str(row.id), actor_id=principal.actor_id, details={"ok": result.ok, "mode": result.mode}, severity="info" if result.ok else "warning")
    db.commit()
    return ConnectionTestOut(ok=result.ok, mode=result.mode, provider=result.provider, message=result.message, details=result.details)


@router.post("/{integration_id}/sync", response_model=IntegrationOut, summary="Record a synchronization checkpoint")
def sync_integration(integration_id: str, principal: Principal = Depends(require("integrations:admin")), db: Session = Depends(get_db)) -> IntegrationOut:
    row = db.get(Integration, uuid.UUID(integration_id))
    if row is None or row.tenant_id != principal.tenant.id:
        raise NotFound("Integration not found")
    row.last_sync_at = datetime.now(UTC)
    db.commit()
    return integration_out(row)
