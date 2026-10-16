"""Tenant administration: settings, emergency disable, users, roles, API keys, tenant onboarding."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.schemas import (
    ApiKeyIn,
    ApiKeyOut,
    RoleIn,
    RoleOut,
    TenantIn,
    TenantOut,
    TenantUpdateIn,
    UserIn,
    UserOut,
    UserUpdateIn,
)
from app.api.serializers import tenant_out, user_out
from app.core.errors import AuthorizationError, Conflict, NotFound, ValidationFailed
from app.core.security import generate_api_key, hash_password
from app.db.models import ApiKey, Role, Tenant, User, UserRole
from app.db.session import get_db
from app.seed.roles import ALL_PERMISSIONS, SYSTEM_ROLES, ensure_system_roles
from app.services.audit import record_audit

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/tenant", response_model=TenantOut, summary="Current tenant")
def get_tenant(principal: Principal = Depends(require("tenant:read"))) -> TenantOut:
    return tenant_out(principal.tenant)


@router.patch("/tenant", response_model=TenantOut, summary="Update tenant settings, quotas, retention, emergency disable")
def update_tenant(body: TenantUpdateIn, principal: Principal = Depends(require("tenant:admin")), db: Session = Depends(get_db)) -> TenantOut:
    t = db.get(Tenant, principal.tenant.id)
    assert t is not None
    changes = body.model_dump(exclude_unset=True)
    if "quotas" in changes and not principal.has("platform:admin"):
        raise AuthorizationError("Only platform administrators can change quotas")
    if "plan" in changes and not principal.has("platform:admin"):
        raise AuthorizationError("Only platform administrators can change plans")
    if "settings" in changes:
        # Merge one level deep so a form that edits some policy keys (e.g. approval_mode) does not
        # wipe keys it does not show (e.g. policies.denied_tools, set via the API).
        merged = dict(t.settings or {})
        for key, value in (changes.pop("settings") or {}).items():
            merged[key] = {**merged[key], **value} if isinstance(value, dict) and isinstance(merged.get(key), dict) else value
        t.settings = merged
    for k, v in changes.items():
        setattr(t, k, v)
    severity = "critical" if body.emergency_disabled is not None else "info"
    record_audit(db, tenant_id=t.id, action="tenant.updated" if body.emergency_disabled is None else ("tenant.emergency_disabled" if body.emergency_disabled else "tenant.emergency_enabled"), resource_type="tenant", resource_id=str(t.id), actor_id=principal.actor_id, details=body.model_dump(exclude_unset=True, mode="json"), severity=severity)
    db.commit()
    return tenant_out(t)


@router.get("/permissions", summary="Permission catalog")
def permissions(principal: Principal = Depends(require("roles:read"))) -> dict:
    return {"permissions": ALL_PERMISSIONS, "system_roles": SYSTEM_ROLES}


# --- Users -------------------------------------------------------------------
@router.get("/users", response_model=list[UserOut], summary="List users")
def list_users(principal: Principal = Depends(require("users:read")), db: Session = Depends(get_db)) -> list[UserOut]:
    rows = db.execute(select(User).where(User.tenant_id == principal.tenant.id).order_by(User.full_name)).scalars().all()
    return [user_out(u) for u in rows]


def _roles_by_name(db: Session, tenant_id: uuid.UUID, names: list[str]) -> list[Role]:
    roles = db.execute(select(Role).where(Role.tenant_id == tenant_id, Role.name.in_(names))).scalars().all()
    missing = set(names) - {r.name for r in roles}
    if missing:
        raise ValidationFailed(f"Unknown roles: {', '.join(sorted(missing))}")
    return list(roles)


def _guard_privilege_escalation(principal: Principal, roles: list[Role]) -> None:
    for r in roles:
        for p in r.permissions or []:
            if not principal.has(p):
                raise AuthorizationError(f"You cannot grant role '{r.name}' because you lack '{p}'")


@router.post("/users", response_model=UserOut, status_code=201, summary="Invite/create a user")
def create_user(body: UserIn, principal: Principal = Depends(require("users:admin")), db: Session = Depends(get_db)) -> UserOut:
    if db.execute(select(User).where(User.tenant_id == principal.tenant.id, User.email == body.email.lower())).scalar_one_or_none():
        raise Conflict("A user with this email already exists")
    roles = _roles_by_name(db, principal.tenant.id, body.roles or ["viewer"])
    _guard_privilege_escalation(principal, roles)
    u = User(tenant_id=principal.tenant.id, email=body.email.lower(), full_name=body.full_name, hashed_password=hash_password(body.password) if body.password else None, external_subject=body.external_subject)
    u.roles = roles
    db.add(u)
    db.flush()
    record_audit(db, tenant_id=principal.tenant.id, action="user.created", resource_type="user", resource_id=str(u.id), actor_id=principal.actor_id, details={"email": u.email, "roles": [r.name for r in roles]})
    db.commit()
    return user_out(u)


@router.patch("/users/{user_id}", response_model=UserOut, summary="Update a user")
def update_user(user_id: str, body: UserUpdateIn, principal: Principal = Depends(require("users:admin")), db: Session = Depends(get_db)) -> UserOut:
    u = db.get(User, uuid.UUID(user_id))
    if u is None or u.tenant_id != principal.tenant.id:
        raise NotFound("User not found")
    if body.roles is not None:
        roles = _roles_by_name(db, principal.tenant.id, body.roles)
        _guard_privilege_escalation(principal, roles)
        if principal.user and u.id == principal.user.id and "admin" not in body.roles and "admin" in principal.roles:
            raise ValidationFailed("You cannot remove your own admin role")
        u.roles = roles
    if body.full_name is not None:
        u.full_name = body.full_name
    if body.is_active is not None:
        if principal.user and u.id == principal.user.id and not body.is_active:
            raise ValidationFailed("You cannot deactivate yourself")
        u.is_active = body.is_active
    if body.password:
        u.hashed_password = hash_password(body.password)
    record_audit(db, tenant_id=principal.tenant.id, action="user.updated", resource_type="user", resource_id=str(u.id), actor_id=principal.actor_id, details=body.model_dump(exclude_unset=True, exclude={"password"}))
    db.commit()
    return user_out(u)


# --- Roles -------------------------------------------------------------------
@router.get("/roles", response_model=list[RoleOut], summary="List roles")
def list_roles(principal: Principal = Depends(require("roles:read")), db: Session = Depends(get_db)) -> list[RoleOut]:
    roles = db.execute(select(Role).where(Role.tenant_id == principal.tenant.id).order_by(Role.name)).scalars().all()
    counts = dict(db.execute(select(UserRole.role_id, func.count()).group_by(UserRole.role_id)).all())
    return [RoleOut(id=str(r.id), name=r.name, description=r.description, permissions=r.permissions or [], is_system=r.is_system, user_count=counts.get(r.id, 0)) for r in roles]


@router.post("/roles", response_model=RoleOut, status_code=201, summary="Create a custom role")
def create_role(body: RoleIn, principal: Principal = Depends(require("roles:admin")), db: Session = Depends(get_db)) -> RoleOut:
    unknown = [p for p in body.permissions if p not in ALL_PERMISSIONS and not p.endswith(":*")]
    if unknown:
        raise ValidationFailed(f"Unknown permissions: {', '.join(unknown)}")
    for p in body.permissions:
        if not principal.has(p):
            raise AuthorizationError(f"You cannot grant '{p}'")
    if db.execute(select(Role).where(Role.tenant_id == principal.tenant.id, Role.name == body.name)).scalar_one_or_none():
        raise Conflict("Role already exists")
    r = Role(tenant_id=principal.tenant.id, name=body.name, description=body.description, permissions=sorted(set(body.permissions)))
    db.add(r)
    db.flush()
    record_audit(db, tenant_id=principal.tenant.id, action="role.created", resource_type="role", resource_id=str(r.id), actor_id=principal.actor_id, details={"permissions": r.permissions})
    db.commit()
    return RoleOut(id=str(r.id), name=r.name, description=r.description, permissions=r.permissions, is_system=False)


# --- API keys ------------------------------------------------------------------
@router.get("/api-keys", response_model=list[ApiKeyOut], summary="List API keys")
def list_keys(principal: Principal = Depends(require("apikeys:admin")), db: Session = Depends(get_db)) -> list[ApiKeyOut]:
    rows = db.execute(select(ApiKey).where(ApiKey.tenant_id == principal.tenant.id).order_by(ApiKey.created_at.desc())).scalars().all()
    return [ApiKeyOut(id=str(k.id), name=k.name, prefix=k.prefix, scopes=k.scopes, created_at=k.created_at, expires_at=k.expires_at, last_used_at=k.last_used_at, revoked_at=k.revoked_at) for k in rows]


@router.post("/api-keys", response_model=ApiKeyOut, status_code=201, summary="Create an API key (plaintext shown once)")
def create_key(body: ApiKeyIn, principal: Principal = Depends(require("apikeys:admin")), db: Session = Depends(get_db)) -> ApiKeyOut:
    for s in body.scopes:
        if not principal.has(s):
            raise AuthorizationError(f"You cannot grant scope '{s}'")
    plaintext, prefix, digest = generate_api_key()
    k = ApiKey(tenant_id=principal.tenant.id, name=body.name, prefix=prefix, key_hash=digest, scopes=body.scopes, created_by=principal.user.id if principal.user else None, expires_at=datetime.now(UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days else None)
    db.add(k)
    db.flush()
    record_audit(db, tenant_id=principal.tenant.id, action="apikey.created", resource_type="api_key", resource_id=str(k.id), actor_id=principal.actor_id, details={"prefix": prefix, "scopes": body.scopes})
    db.commit()
    return ApiKeyOut(id=str(k.id), name=k.name, prefix=prefix, scopes=k.scopes, created_at=k.created_at, expires_at=k.expires_at, plaintext=plaintext)


@router.delete("/api-keys/{key_id}", status_code=204, summary="Revoke an API key", response_class=Response)
def revoke_key(key_id: str, principal: Principal = Depends(require("apikeys:admin")), db: Session = Depends(get_db)) -> Response:
    k = db.get(ApiKey, uuid.UUID(key_id))
    if k is None or k.tenant_id != principal.tenant.id:
        raise NotFound("API key not found")
    k.revoked_at = datetime.now(UTC)
    record_audit(db, tenant_id=principal.tenant.id, action="apikey.revoked", resource_type="api_key", resource_id=str(k.id), actor_id=principal.actor_id, severity="warning")
    db.commit()
    return Response(status_code=204)


# --- Platform: tenant onboarding --------------------------------------------------
@router.get("/tenants", response_model=list[TenantOut], summary="List tenants (platform admins)")
def list_tenants(principal: Principal = Depends(require("platform:admin")), db: Session = Depends(get_db)) -> list[TenantOut]:
    return [tenant_out(t) for t in db.execute(select(Tenant).order_by(Tenant.created_at)).scalars().all()]


@router.post("/tenants", response_model=TenantOut, status_code=201, summary="Onboard a new tenant (platform admins)")
def create_tenant(body: TenantIn, principal: Principal = Depends(require("platform:admin")), db: Session = Depends(get_db)) -> TenantOut:
    if db.execute(select(Tenant).where(Tenant.slug == body.slug)).scalar_one_or_none():
        raise Conflict("Tenant slug already taken")
    t = Tenant(slug=body.slug, name=body.name, plan=body.plan, settings={"policies": {"approval_mode": "standard", "amount_threshold": 1000, "separation_of_duties": True}}, quotas={}, feature_flags={})
    db.add(t)
    db.flush()
    roles = ensure_system_roles(db, t.id)
    admin = User(tenant_id=t.id, email=body.admin_email.lower(), full_name=body.admin_name, hashed_password=hash_password(body.admin_password) if body.admin_password else None)
    admin.roles = [roles["admin"]]
    db.add(admin)
    db.flush()
    record_audit(db, tenant_id=t.id, action="tenant.created", resource_type="tenant", resource_id=str(t.id), actor_id=principal.actor_id, details={"slug": t.slug, "plan": t.plan})
    db.commit()
    return tenant_out(t)
