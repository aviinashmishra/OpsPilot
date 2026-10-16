"""FastAPI dependencies: authentication, tenant resolution, permission checks.

Tenant identity is always derived from the verified credential (JWT claims or
the API key row) - never from client-supplied headers or body fields.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AuthenticationError, AuthorizationError
from app.core.logging import tenant_id_var
from app.core.security import decode_token, hash_api_key
from app.db.models import ApiKey, Role, Tenant, User
from app.db.session import get_db, set_tenant_context

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    tenant: Tenant
    user: User | None
    actor_id: str
    actor_type: str  # user|api_key
    permissions: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)

    def has(self, perm: str) -> bool:
        if perm == "platform:admin":  # never implied by wildcards: must be granted explicitly
            return perm in self.permissions
        if "*" in self.permissions or perm in self.permissions:
            return True
        return f"{perm.split(':')[0]}:*" in self.permissions

    @property
    def is_admin(self) -> bool:
        return "*" in self.permissions or "admin" in self.roles


def _permissions_for_user(user: User) -> tuple[list[str], list[str]]:
    perms: set[str] = set()
    roles: list[str] = []
    for role in user.roles:
        roles.append(role.name)
        perms.update(role.permissions or [])
    return sorted(perms), roles


def get_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> Principal:
    if x_api_key:
        row = db.execute(select(ApiKey).where(ApiKey.key_hash == hash_api_key(x_api_key))).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            raise AuthenticationError("Invalid API key")
        if row.expires_at and row.expires_at.replace(tzinfo=row.expires_at.tzinfo or UTC) < datetime.now(UTC):
            raise AuthenticationError("API key expired")
        tenant = db.get(Tenant, row.tenant_id)
        if tenant is None or tenant.status != "active":
            raise AuthenticationError("Tenant inactive")
        row.last_used_at = datetime.now(UTC)
        db.commit()
        set_tenant_context(db, str(tenant.id))
        tenant_id_var.set(str(tenant.id))
        return Principal(tenant=tenant, user=None, actor_id=f"apikey:{row.prefix}", actor_type="api_key", permissions=list(row.scopes or []), roles=["api_key"])

    if creds is None or not creds.credentials:
        raise AuthenticationError("Missing bearer token")
    claims = decode_token(creds.credentials)
    tenant_id = claims.get("tid")
    subject = claims.get("sub")
    if not tenant_id or not subject:
        raise AuthenticationError("Token lacks tenant/subject claims")
    tenant = db.get(Tenant, uuid.UUID(str(tenant_id)))
    if tenant is None or tenant.status != "active":
        raise AuthenticationError("Tenant inactive")
    user: User | None = None
    try:
        user = db.get(User, uuid.UUID(str(subject)))
    except ValueError:
        user = db.execute(select(User).where(User.tenant_id == tenant.id, User.external_subject == str(subject))).scalar_one_or_none()
    if user is None or user.tenant_id != tenant.id or not user.is_active:
        raise AuthenticationError("User not found or inactive")
    perms, roles = _permissions_for_user(user)
    set_tenant_context(db, str(tenant.id))
    tenant_id_var.set(str(tenant.id))
    return Principal(tenant=tenant, user=user, actor_id=str(user.id), actor_type="user", permissions=perms, roles=roles)


def require(*perms: str):
    def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        for p in perms:
            if not principal.has(p):
                raise AuthorizationError(f"Missing permission '{p}'")
        return principal

    return _dep


def ensure_role_exists(db: Session, tenant_id: uuid.UUID, name: str) -> Role | None:
    return db.execute(select(Role).where(Role.tenant_id == tenant_id, Role.name == name)).scalar_one_or_none()
