"""Self-serve sign-up: a new company gets a working, isolated workspace in one request."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.api.routes import auth as auth_routes
from app.core.config import get_settings
from app.db.models import Document, Integration, Tenant
from app.seed.demo import DEMO_PASSWORD


@pytest.fixture(autouse=True)
def _no_signup_rate_limit(monkeypatch):
    monkeypatch.setattr(auth_routes, "check_rate_limit", lambda *a, **k: None)


def _signup(client, **over):
    email = over.pop("email", f"owner-{uuid.uuid4().hex[:8]}@newco.test")
    body = {"company": "Northwind Traders", "full_name": "Nora North", "email": email, "password": "Strong-Pass-2026", **over}
    return client.post("/api/v1/auth/signup", json=body), email


def test_signup_creates_a_ready_to_use_isolated_workspace(client, db, admin_headers):
    r, email = _signup(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["access_token"] and body["user"]["email"] == email and "admin" in body["user"]["roles"]
    slug = body["tenant"]["slug"]
    assert slug.startswith("northwind-traders") and body["tenant"]["plan"] == "starter"
    tenant = db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one()
    assert db.execute(select(func.count()).select_from(Integration).where(Integration.tenant_id == tenant.id, Integration.mode == "mock")).scalar_one() == 13
    assert db.execute(select(func.count()).select_from(Document).where(Document.tenant_id == tenant.id)).scalar_one() >= 1
    h = {"Authorization": f"Bearer {body['access_token']}"}

    # Agents work out of the box on the sandbox sample data.
    detail = client.get("/api/v1/agents/customer_support", headers=h).json()
    run = client.post("/api/v1/agents/customer_support/run", json={"input": detail["example_input"], "mode": "direct"}, headers=h)
    assert run.status_code == 200 and run.json()["status"] != "failed", run.text

    # Isolation: the new workspace sees none of the demo tenant's runs, and vice versa.
    demo_runs = {x["id"] for x in client.get("/api/v1/workflows", headers=admin_headers).json()["items"]}
    mine = {x["id"] for x in client.get("/api/v1/workflows", headers=h).json()["items"]}
    assert not demo_runs & mine


def test_signup_validation(client, monkeypatch):
    r, email = _signup(client)
    assert r.status_code == 201
    dup, _ = _signup(client, email=email.upper())
    assert dup.status_code == 409 and dup.json()["error"]["details"]["field"] == "email"
    weak, _ = _signup(client, password="short1")
    assert weak.status_code == 422 and weak.json()["error"]["details"]["field"] == "password"
    letters, _ = _signup(client, password="onlylettershere")
    assert letters.status_code == 422
    monkeypatch.setattr(get_settings(), "allow_signup", False)
    off, _ = _signup(client)
    assert off.status_code == 401


def test_login_without_workspace_name(client):
    r, email = _signup(client)
    assert r.status_code == 201
    ok = client.post("/api/v1/auth/login", json={"email": email, "password": "Strong-Pass-2026"})
    assert ok.status_code == 200 and ok.json()["tenant"]["slug"] == r.json()["tenant"]["slug"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password-1"}).status_code == 401
    # Demo accounts still sign in with or without the workspace.
    assert client.post("/api/v1/auth/login", json={"email": "admin@acme-demo.test", "password": DEMO_PASSWORD}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"tenant": "acme-demo", "email": "admin@acme-demo.test", "password": DEMO_PASSWORD}).status_code == 200


def test_same_email_in_two_workspaces_needs_the_workspace(client, admin_headers):
    shared = f"shared-{uuid.uuid4().hex[:6]}@acme-demo.test"
    created = client.post("/api/v1/admin/users", json={"email": shared, "full_name": "Shared", "password": "Strong-Pass-2026", "roles": ["viewer"]}, headers=admin_headers)
    assert created.status_code in (200, 201), created.text
    other = client.post("/api/v1/auth/signup", json={"company": "Other Shared", "full_name": "S", "email": f"x-{uuid.uuid4().hex[:6]}@o.test", "password": "Strong-Pass-2026"}).json()
    h = {"Authorization": f"Bearer {other['access_token']}"}
    client.post("/api/v1/admin/users", json={"email": shared, "full_name": "Shared", "password": "Strong-Pass-2026", "roles": ["viewer"]}, headers=h)
    amb = client.post("/api/v1/auth/login", json={"email": shared, "password": "Strong-Pass-2026"})
    assert amb.status_code == 409 and amb.json()["error"]["details"]["field"] == "tenant"
    assert client.post("/api/v1/auth/login", json={"tenant": "acme-demo", "email": shared, "password": "Strong-Pass-2026"}).status_code == 200


def test_onboarding_checklist_completes_itself(client):
    r, _ = _signup(client)
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    first = client.get("/api/v1/onboarding", headers=h).json()
    assert first["done"] == 0 and first["total"] == 6 and first["sandbox"] is True
    detail = client.get("/api/v1/agents/lead_qualification", headers=h).json()
    client.post("/api/v1/agents/lead_qualification/run", json={"input": detail["example_input"], "mode": "direct"}, headers=h)
    client.post("/api/v1/admin/users", json={"email": f"mate-{uuid.uuid4().hex[:6]}@newco.test", "full_name": "Mate", "password": "Strong-Pass-2026", "roles": ["approver"]}, headers=h)
    after = client.get("/api/v1/onboarding", headers=h).json()
    done = {s["key"] for s in after["steps"] if s["done"]}
    assert {"agent", "team"} <= done and after["done"] >= 2
