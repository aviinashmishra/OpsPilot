"""Shared fixtures: isolated SQLite database per test session, seeded demo tenant,
FastAPI test client, authenticated headers per role, and a second tenant for
isolation tests. The LLM provider is always the deterministic mock.

Set TEST_DATABASE_URL to run the same suite against an empty PostgreSQL database
(schema built by the Alembic migrations, as in production)."""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="opspilot-test-"))
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(_TMP / 'test.db').as_posix()}",
        "WORKER_MODE": "inline",
        "LLM_PROVIDER": "mock",
        "SECRET_KEY": "test-secret-key-0000000000000000000000000000",
        "DOCUMENT_STORAGE_PATH": str(_TMP / "storage"),
        "LOG_LEVEL": "ERROR",
        "RATE_LIMIT_PER_MINUTE": "100000",
        "WEBHOOK_SIGNING_SECRET": "whsec_test",
    }
)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import reset_settings_cache  # noqa: E402

reset_settings_cache()

import app.tools.catalog  # noqa: E402,F401
from app.agents.registry import agent_registry  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.models import Tenant, User  # noqa: E402
from app.db.session import create_all, get_sessionmaker, reset_engine  # noqa: E402
from app.seed.catalog import sync_catalog  # noqa: E402
from app.seed.demo import DEMO_PASSWORD, DEMO_TENANT_SLUG, seed_demo  # noqa: E402
from app.seed.roles import ensure_system_roles  # noqa: E402

OTHER_TENANT_SLUG = "other-co"
OTHER_PASSWORD = "Other-Tenant-Pass-2026!"


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    reset_engine(os.environ["DATABASE_URL"])
    if os.environ["DATABASE_URL"].startswith("sqlite"):
        create_all()
    else:  # PostgreSQL: build the schema exactly as production does
        from sqlalchemy import inspect

        from alembic import command
        from alembic.config import Config
        from app.db.session import get_engine

        if inspect(get_engine()).get_table_names():
            pytest.exit("TEST_DATABASE_URL must point to an EMPTY database (tests create and seed their own data)", returncode=2)
        command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    agent_registry.load_builtin()
    db = get_sessionmaker()()
    try:
        sync_catalog(db)
        seed_demo(db)
        other = db.execute(select(Tenant).where(Tenant.slug == OTHER_TENANT_SLUG)).scalar_one_or_none()
        if other is None:
            other = Tenant(slug=OTHER_TENANT_SLUG, name="Other Co", plan="starter", settings={"policies": {"approval_mode": "standard"}}, quotas={}, feature_flags={})
            db.add(other)
            db.flush()
            roles = ensure_system_roles(db, other.id)
            u = User(tenant_id=other.id, email="admin@other-co.test", full_name="Other Admin", hashed_password=hash_password(OTHER_PASSWORD))
            u.roles = [roles["admin"]]
            db.add(u)
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as c:
        yield c


def _login(client: TestClient, tenant: str, email: str, password: str) -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"tenant": tenant, "email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_headers(client: TestClient) -> dict[str, str]:
    return _login(client, DEMO_TENANT_SLUG, "admin@acme-demo.test", DEMO_PASSWORD)


@pytest.fixture(scope="session")
def operator_headers(client: TestClient) -> dict[str, str]:
    return _login(client, DEMO_TENANT_SLUG, "ops@acme-demo.test", DEMO_PASSWORD)


@pytest.fixture(scope="session")
def approver_headers(client: TestClient) -> dict[str, str]:
    return _login(client, DEMO_TENANT_SLUG, "approver@acme-demo.test", DEMO_PASSWORD)


@pytest.fixture(scope="session")
def finance_headers(client: TestClient) -> dict[str, str]:
    return _login(client, DEMO_TENANT_SLUG, "finance@acme-demo.test", DEMO_PASSWORD)


@pytest.fixture(scope="session")
def viewer_headers(client: TestClient) -> dict[str, str]:
    return _login(client, DEMO_TENANT_SLUG, "viewer@acme-demo.test", DEMO_PASSWORD)


@pytest.fixture(scope="session")
def other_headers(client: TestClient) -> dict[str, str]:
    return _login(client, OTHER_TENANT_SLUG, "admin@other-co.test", OTHER_PASSWORD)


@pytest.fixture
def db():
    s = get_sessionmaker()()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def demo_tenant(db) -> Tenant:
    return db.execute(select(Tenant).where(Tenant.slug == DEMO_TENANT_SLUG)).scalar_one()


def idem() -> str:
    return uuid.uuid4().hex
