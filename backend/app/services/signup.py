"""Self-serve workspace sign-up.

A new company gets its own tenant, an admin account, safe default policies, a sandbox connection
for every system family and (by default) sample business data, so every agent, workflow and the
Copilot work immediately. Real systems are connected later from Integrations.
"""

from __future__ import annotations

import re
import secrets
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, ValidationFailed
from app.core.security import hash_password
from app.db.models import Tenant, User
from app.db.session import set_tenant_context
from app.seed.demo import default_tenant_settings, provision_workspace
from app.seed.roles import ensure_system_roles
from app.services.audit import record_audit

SELF_SERVE_PLAN = "starter"
SELF_SERVE_QUOTAS = {"monthly_workflow_runs": 1000, "monthly_llm_tokens": 1_000_000, "max_concurrent_runs": 10}
MIN_PASSWORD_LENGTH = 10
_RESERVED_SLUGS = {"admin", "api", "app", "login", "signup", "help", "www", "mcp", "docs", "acme-demo"}


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:48].strip("-")
    return slug if len(slug) >= 3 else (slug + "-team" if slug else "workspace")


def unique_slug(db: Session, name: str) -> str:
    base = slugify(name)
    candidate = base
    while candidate in _RESERVED_SLUGS or db.execute(select(Tenant.id).where(Tenant.slug == candidate)).first():
        candidate = f"{base}-{secrets.token_hex(2)}"
    return candidate


def check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationFailed(f"Use at least {MIN_PASSWORD_LENGTH} characters for the password", details={"field": "password"})
    if password.isdigit() or password.isalpha():
        raise ValidationFailed("Use a mix of letters and numbers or symbols in the password", details={"field": "password"})


def create_workspace(db: Session, *, company: str, full_name: str, email: str, password: str, sample_data: bool = True, ip_address: str | None = None) -> tuple[Tenant, User]:
    company, full_name, email = company.strip(), full_name.strip(), email.strip().lower()
    if len(company) < 2:
        raise ValidationFailed("Enter your company name", details={"field": "company"})
    if not full_name:
        raise ValidationFailed("Enter your name", details={"field": "full_name"})
    check_password(password)
    if db.execute(select(func.count()).select_from(User).where(User.email == email)).scalar_one():
        raise Conflict("An account with this email already exists. Sign in instead.", details={"field": "email"})

    tenant = Tenant(slug=unique_slug(db, company), name=company, plan=SELF_SERVE_PLAN, status="active", settings=default_tenant_settings(), quotas=dict(SELF_SERVE_QUOTAS), feature_flags={"workflow_builder": True, "evaluations": True}, retention_days=365)
    db.add(tenant)
    db.flush()
    set_tenant_context(db, str(tenant.id))  # PostgreSQL RLS: the rest of this transaction writes as the new tenant
    roles = ensure_system_roles(db, tenant.id)
    user = User(tenant_id=tenant.id, email=email, full_name=full_name, hashed_password=hash_password(password))
    user.roles = [roles["admin"]]
    db.add(user)
    db.flush()
    provision_workspace(db, tenant, sample_data=sample_data)
    record_audit(db, tenant_id=tenant.id, action="tenant.signup", resource_type="tenant", resource_id=str(tenant.id), actor_id=str(user.id), details={"company": company, "sample_data": sample_data}, ip_address=ip_address)
    return tenant, user
