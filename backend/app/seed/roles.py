"""Permission catalog and system roles (least privilege by default)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Role

ALL_PERMISSIONS: list[str] = sorted(
    {
        # platform resources
        "events:read", "events:write",
        "workflows:read", "workflows:write", "workflows:admin",
        "agents:read", "agents:run", "agents:admin",
        "tasks:read", "tasks:write",
        "approvals:read", "approvals:decide",
        "integrations:read", "integrations:admin",
        "reports:read", "usage:read", "audit:read",
        "documents:read", "documents:write",
        "incidents:write",
        "tenant:read", "tenant:admin",
        "users:read", "users:admin", "roles:read", "roles:admin", "apikeys:admin",
        "data:sensitive",
        "platform:admin",
        # tool scopes (what agents may do on behalf of the actor)
        "crm:read", "crm:write", "email:read", "email:send", "chat:read", "chat:write",
        "issues:read", "issues:write", "helpdesk:read", "helpdesk:write",
        "commerce:read", "commerce:write", "accounting:read", "accounting:write",
        "whatsapp:read", "whatsapp:send", "workspace:read", "workspace:write",
        "monitoring:read", "monitoring:write", "procurement:read", "procurement:commit",
        "feedback:read", "metrics:read", "tools:custom",
    }
)

_TOOL_READ = ["crm:read", "email:read", "chat:read", "issues:read", "helpdesk:read", "commerce:read", "accounting:read", "whatsapp:read", "workspace:read", "monitoring:read", "procurement:read", "feedback:read", "metrics:read", "documents:read", "tasks:read"]
_TOOL_WRITE_LOW = ["tools:custom", "crm:write", "chat:write", "issues:write", "helpdesk:write", "commerce:write", "workspace:write", "monitoring:write", "tasks:write", "incidents:write", "workflows:write"]

SYSTEM_ROLES: dict[str, dict] = {
    "admin": {"description": "Full tenant administration (cannot change its own plan/quotas)", "permissions": ["*"]},
    "platform_admin": {"description": "Operator of the OpsPilot deployment: tenant onboarding, plans and quotas", "permissions": ["*", "platform:admin"]},
    "operator": {
        "description": "Runs workflows and agents, manages tasks; cannot change policy or users",
        "permissions": sorted({"events:read", "events:write", "workflows:read", "workflows:write", "agents:read", "agents:run", "approvals:read", "integrations:read", "reports:read", "usage:read", "documents:write", *_TOOL_READ, *_TOOL_WRITE_LOW}),
    },
    "approver": {
        "description": "Reviews and decides consequential actions",
        "permissions": sorted({"approvals:read", "approvals:decide", "workflows:read", "agents:read", "reports:read", "tasks:read", "data:sensitive", "email:send", "whatsapp:send", "accounting:write", "procurement:commit", *_TOOL_READ, *_TOOL_WRITE_LOW}),
    },
    "finance_approver": {
        "description": "Approves finance and procurement commitments",
        "permissions": sorted({"approvals:read", "approvals:decide", "workflows:read", "agents:read", "reports:read", "accounting:read", "accounting:write", "procurement:read", "procurement:commit", "data:sensitive"}),
    },
    "auditor": {"description": "Read-only access to audit trail and reports", "permissions": ["audit:read", "reports:read", "usage:read", "workflows:read", "agents:read", "approvals:read", "integrations:read", "tenant:read", "users:read", "roles:read"]},
    "viewer": {"description": "Read-only dashboards", "permissions": ["workflows:read", "agents:read", "reports:read", "tasks:read", "approvals:read", "integrations:read"]},
}


def ensure_system_roles(db: Session, tenant_id: uuid.UUID) -> dict[str, Role]:
    out: dict[str, Role] = {}
    for name, spec in SYSTEM_ROLES.items():
        role = db.execute(select(Role).where(Role.tenant_id == tenant_id, Role.name == name)).scalar_one_or_none()
        if role is None:
            role = Role(tenant_id=tenant_id, name=name, description=spec["description"], permissions=spec["permissions"], is_system=True)
            db.add(role)
        else:
            role.permissions = spec["permissions"]
            role.description = spec["description"]
        out[name] = role
    db.flush()
    return out
