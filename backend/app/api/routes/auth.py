"""Authentication: local password login (dev issuer) and current-user info.

In production configure OIDC (OIDC_ISSUER / OIDC_JWKS_URL); bearer tokens from
the IdP are then verified against its JWKS and mapped to users by `sub`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.api.schemas import LoginRequest, SignupRequest, TokenResponse, UserOut
from app.api.serializers import tenant_out, user_out
from app.core.config import get_settings
from app.core.errors import AuthenticationError, Conflict
from app.core.ratelimit import check_rate_limit
from app.core.security import create_access_token, verify_password
from app.db.models import Tenant, User
from app.db.session import get_db
from app.services.audit import record_audit
from app.services.signup import create_workspace

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse, summary="Password login (local issuer)")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    s = get_settings()
    if not s.allow_password_login:
        raise AuthenticationError("Password login is disabled; use SSO")
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(f"login:{client_ip}", limit=20)
    email = body.email.lower()
    tenant, user = (_find_in_workspace(db, body.tenant.strip().lower(), email) if body.tenant and body.tenant.strip() else _find_by_email(db, email, body.password))
    if tenant is None or user is None or not user.is_active or not verify_password(body.password, user.hashed_password):
        if tenant is not None:
            record_audit(db, tenant_id=tenant.id, action="auth.login_failed", resource_type="user", actor_type="user", details={"email": body.email}, severity="warning", ip_address=client_ip)
            db.commit()
        raise AuthenticationError("Invalid credentials")
    if tenant.status != "active":
        raise AuthenticationError("Tenant is not active")
    return _issue(db, tenant, user, client_ip, action="auth.login")


def _find_in_workspace(db: Session, slug: str, email: str) -> tuple[Tenant | None, User | None]:
    tenant = db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
    if tenant is None:
        return None, None
    return tenant, db.execute(select(User).where(User.tenant_id == tenant.id, User.email == email)).scalar_one_or_none()


def _find_by_email(db: Session, email: str, password: str) -> tuple[Tenant | None, User | None]:
    """Workspace omitted: use the single workspace this email/password belongs to."""
    matches = [u for u in db.execute(select(User).where(User.email == email, User.is_active.is_(True))).scalars().all() if verify_password(password, u.hashed_password)]
    if len(matches) > 1:
        raise Conflict("This email belongs to several workspaces. Enter the workspace name to sign in.", details={"field": "tenant"})
    if not matches:
        return None, None
    return db.get(Tenant, matches[0].tenant_id), matches[0]


def _issue(db: Session, tenant: Tenant, user: User, client_ip: str, *, action: str) -> TokenResponse:
    s = get_settings()
    out = user_out(user)
    token = create_access_token(subject=str(user.id), tenant_id=str(tenant.id), roles=out.roles, permissions=out.permissions)
    user.last_login_at = datetime.now(UTC)
    record_audit(db, tenant_id=tenant.id, action=action, resource_type="user", resource_id=str(user.id), actor_id=str(user.id), ip_address=client_ip)
    db.commit()
    return TokenResponse(access_token=token, expires_in=s.access_token_ttl_minutes * 60, user=out, tenant=tenant_out(tenant))


@router.post("/signup", response_model=TokenResponse, status_code=201, summary="Create a workspace for a new company (self-serve) and sign in")
def signup(body: SignupRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    s = get_settings()
    if not s.allow_signup or not s.allow_password_login:
        raise AuthenticationError("Self-serve sign-up is disabled on this installation")
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(f"signup:{client_ip}", limit=5)
    tenant, user = create_workspace(db, company=body.company, full_name=body.full_name, email=body.email, password=body.password, sample_data=body.sample_data, ip_address=client_ip)
    db.commit()
    return _issue(db, tenant, user, client_ip, action="auth.login")


@router.get("/me", response_model=TokenResponse, summary="Current principal")
def me(principal: Principal = Depends(get_principal)) -> TokenResponse:
    if principal.user is None:
        raise AuthenticationError("API keys have no user profile")
    return TokenResponse(access_token="", expires_in=0, user=user_out(principal.user), tenant=tenant_out(principal.tenant))


@router.get("/demo-accounts", summary="List seeded demo accounts (development only)")
def demo_accounts() -> dict:
    s = get_settings()
    if s.is_production:
        return {"accounts": []}
    from app.seed.demo import DEMO_PASSWORD, DEMO_TENANT_SLUG, DEMO_USERS

    # Only the public default is ever revealed; a custom DEMO_PASSWORD must be typed in.
    return {
        "tenant": DEMO_TENANT_SLUG,
        "password": None if s.demo_password else DEMO_PASSWORD,
        "accounts": [{"email": u["email"], "role": u["roles"][0], "name": u["full_name"]} for u in DEMO_USERS],
    }


UserOut  # noqa: B018 - re-export for OpenAPI
