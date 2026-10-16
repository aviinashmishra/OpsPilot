"""Business events and provider webhooks.

* POST /events            authenticated ingestion (API key or user token)
* POST /webhooks/{tenant}/{provider}   signed webhooks (HMAC), tenant resolved
                                       from the path and verified via the
                                       integration's stored webhook secret
* GET  /webhooks/{tenant}/whatsapp     Meta webhook verification handshake
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.schemas import EventIn, EventOut, Page
from app.core.config import get_settings
from app.core.errors import AuthenticationError, NotFound, ValidationFailed
from app.core.ratelimit import check_rate_limit
from app.core.security import (
    canonical_hash,
    decrypt_secret,
    verify_hmac_sha256,
    verify_hmac_sha256_base64,
    verify_signature,
)
from app.db.models import BusinessEvent, Integration, Tenant
from app.db.session import get_db
from app.orchestration.definitions import EVENT_ROUTING
from app.orchestration.engine import start_run
from app.services.audit import record_audit

router = APIRouter(tags=["events"])

MAX_EVENT_BYTES = 512 * 1024


def _event_out(e: BusinessEvent, duplicate: bool = False) -> EventOut:
    return EventOut(
        id=str(e.id), status=e.status, event_type=e.event_type, source=e.source, dedupe_key=e.dedupe_key,
        workflow_run_id=str(e.workflow_run_id) if e.workflow_run_id else None, duplicate=duplicate,
        received_at=e.received_at if e.received_at.tzinfo else e.received_at.replace(tzinfo=UTC),
    )


def ingest_event(db: Session, tenant: Tenant, body: EventIn, actor_id: str, idempotency_key: str | None = None) -> EventOut:
    raw = json.dumps(body.payload, default=str)
    if len(raw.encode()) > MAX_EVENT_BYTES:
        raise ValidationFailed("Event payload too large", details={"max_bytes": MAX_EVENT_BYTES})
    dedupe_key = idempotency_key or (f"{body.source}:{body.event_type}:{body.external_id}" if body.external_id else f"{body.source}:{body.event_type}:{canonical_hash(body.payload)[:40]}")
    existing = db.execute(select(BusinessEvent).where(BusinessEvent.tenant_id == tenant.id, BusinessEvent.dedupe_key == dedupe_key)).scalar_one_or_none()
    if existing:
        return _event_out(existing, duplicate=True)

    evt = BusinessEvent(tenant_id=tenant.id, source=body.source, event_type=body.event_type, external_id=body.external_id, dedupe_key=dedupe_key, payload=body.payload, status="received")
    db.add(evt)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.execute(select(BusinessEvent).where(BusinessEvent.tenant_id == tenant.id, BusinessEvent.dedupe_key == dedupe_key)).scalar_one()
        return _event_out(existing, duplicate=True)
    record_audit(db, tenant_id=tenant.id, action="event.received", resource_type="business_event", resource_id=str(evt.id), actor_id=actor_id, actor_type="api_key" if actor_id.startswith("apikey:") else "user", details={"type": body.event_type, "source": body.source})
    db.commit()

    workflow_key = body.workflow_key or EVENT_ROUTING.get(body.event_type)
    if not workflow_key:
        evt.status = "unrouted"
        db.commit()
        return _event_out(evt)
    try:
        run = start_run(db, tenant_id=str(tenant.id), workflow_key=workflow_key, input=_workflow_input(body), actor_id=actor_id, idempotency_key=f"event:{evt.id}", trigger_event_id=str(evt.id))
        evt.workflow_run_id = run.id
        evt.status = "dispatched"
        evt.processed_at = datetime.now(UTC)
    except Exception as exc:  # noqa: BLE001
        evt.status = "failed"
        evt.error = str(exc)[:500]
    db.commit()
    return _event_out(evt)


def _workflow_input(body: EventIn) -> dict[str, Any]:
    p = dict(body.payload)
    p.setdefault("source", body.source)
    p.setdefault("event_type", body.event_type)
    return p


@router.post("/events", response_model=EventOut, status_code=202, summary="Ingest a business event (deduplicated)")
def post_event(body: EventIn, request: Request, principal: Principal = Depends(require("events:write")), db: Session = Depends(get_db)) -> EventOut:
    check_rate_limit(f"events:{principal.tenant.id}")
    idem = request.headers.get("Idempotency-Key")
    return ingest_event(db, principal.tenant, body, principal.actor_id, idem)


@router.get("/events", response_model=Page[EventOut], summary="List business events")
def list_events(
    request: Request,
    status: str | None = None,
    event_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require("events:read")),
    db: Session = Depends(get_db),
) -> Page[EventOut]:
    stmt = select(BusinessEvent).where(BusinessEvent.tenant_id == principal.tenant.id)
    if status:
        stmt = stmt.where(BusinessEvent.status == status)
    if event_type:
        stmt = stmt.where(BusinessEvent.event_type == event_type)
    total = len(db.execute(stmt).scalars().all())
    rows = db.execute(stmt.order_by(BusinessEvent.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return Page(items=[_event_out(e) for e in rows], total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


def _tenant_by_slug(db: Session, slug: str) -> Tenant:
    tenant = db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
    if tenant is None or tenant.status != "active":
        raise NotFound("Unknown tenant")
    return tenant


def _webhook_secret(db: Session, tenant: Tenant, provider: str) -> str | None:
    integ = db.execute(select(Integration).where(Integration.tenant_id == tenant.id, Integration.provider == provider)).scalars().first()
    if integ and integ.webhook_secret_encrypted:
        return decrypt_secret(integ.webhook_secret_encrypted)
    return get_settings().webhook_signing_secret


@router.get("/webhooks/{tenant_slug}/whatsapp", summary="WhatsApp (Meta) webhook verification handshake")
def whatsapp_verify(
    tenant_slug: str,
    request: Request,
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    db: Session = Depends(get_db),
) -> Response:
    tenant = _tenant_by_slug(db, tenant_slug)
    integ = db.execute(select(Integration).where(Integration.tenant_id == tenant.id, Integration.provider == "whatsapp")).scalars().first()
    expected = (integ.config or {}).get("verify_token") if integ else None
    if hub_mode == "subscribe" and expected and hub_verify_token == expected and hub_challenge:
        return Response(content=hub_challenge, media_type="text/plain")
    raise AuthenticationError("Webhook verification failed")


@router.post("/webhooks/{tenant_slug}/{provider}", response_model=EventOut, status_code=202, summary="Signed provider webhook")
async def provider_webhook(tenant_slug: str, provider: str, request: Request, db: Session = Depends(get_db)) -> EventOut:
    body = await request.body()
    if len(body) > MAX_EVENT_BYTES:
        raise ValidationFailed("Payload too large")
    tenant = _tenant_by_slug(db, tenant_slug)
    check_rate_limit(f"webhook:{tenant.id}:{provider}")
    secret = _webhook_secret(db, tenant, provider)
    if not secret:
        raise AuthenticationError("Webhook secret not configured for this provider")

    ok = False
    if provider == "whatsapp":
        ok = verify_hmac_sha256(secret, body, request.headers.get("X-Hub-Signature-256"), prefix="sha256=")
    elif provider == "commerce":
        ok = verify_hmac_sha256_base64(secret, body, request.headers.get("X-Shopify-Hmac-Sha256")) or verify_signature(secret, body, request.headers.get("X-OpsPilot-Signature"))
    else:
        ok = verify_signature(secret, body, request.headers.get("X-OpsPilot-Signature"))
    if not ok:
        record_audit(db, tenant_id=tenant.id, action="webhook.signature_invalid", resource_type="webhook", actor_type="system", details={"provider": provider}, severity="warning")
        db.commit()
        raise AuthenticationError("Invalid webhook signature")

    try:
        data = json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        raise ValidationFailed("Webhook body must be JSON") from exc
    event = _normalize_webhook(provider, data, request)
    return ingest_event(db, tenant, event, actor_id=f"webhook:{provider}")


def _normalize_webhook(provider: str, data: dict[str, Any], request: Request) -> EventIn:
    if provider == "whatsapp":
        # Meta Cloud API shape: entry[].changes[].value.messages[]
        try:
            value = data["entry"][0]["changes"][0]["value"]
            msg = value["messages"][0]
            return EventIn(
                source="whatsapp",
                event_type="whatsapp.message_received",
                external_id=msg.get("id"),
                payload={"message": (msg.get("text") or {}).get("body", ""), "phone": msg.get("from"), "channel": "whatsapp", "customer_id": None, "raw_type": msg.get("type")},
            )
        except (KeyError, IndexError, TypeError):
            return EventIn(source="whatsapp", event_type="whatsapp.status_update", external_id=None, payload={"raw": data})
    if provider == "commerce":
        topic = request.headers.get("X-Shopify-Topic", data.get("event_type", "order.updated"))
        mapping = {"orders/updated": "order.updated", "orders/create": "order.created", "fulfillments/update": "shipment.delayed"}
        return EventIn(source="commerce", event_type=mapping.get(topic, topic), external_id=str(data.get("id") or uuid.uuid4()), payload=data.get("payload", data))
    return EventIn(source=provider, event_type=str(data.get("event_type", f"{provider}.event")), external_id=data.get("external_id") or data.get("id"), payload=data.get("payload", data))
