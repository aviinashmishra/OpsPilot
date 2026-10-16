"""Regressions found while building the dashboard: malformed ids, tenant scoping of queue data,
timezone-explicit timestamps, and double-encoded text in source files."""

import re
import uuid
from pathlib import Path

import pytest

from app.db.models import Job
from tests.conftest import idem


@pytest.mark.parametrize("method,path", [("get", "/api/v1/batches/not-a-uuid"), ("post", "/api/v1/batches/not-a-uuid/cancel"), ("post", "/api/v1/system/jobs/not-a-uuid/retry")])
def test_malformed_ids_are_404_not_500(client, admin_headers, method, path):
    r = getattr(client, method)(path, headers=admin_headers)
    assert r.status_code == 404, r.text


def test_queue_view_only_counts_own_tenant(client, admin_headers, other_headers, db):
    other_tenant_id = uuid.UUID(client.get("/api/v1/auth/me", headers=other_headers).json()["tenant"]["id"])
    before = client.get("/api/v1/system/queue", headers=admin_headers).json()
    db.add(Job(kind="maintenance", payload={}, tenant_id=other_tenant_id, status="dead", attempts=5, max_attempts=5, dedupe_key=f"other:{idem()}"))
    db.commit()
    after = client.get("/api/v1/system/queue", headers=admin_headers).json()
    assert after["by_status"]["dead"] == before["by_status"]["dead"]  # another tenant's job is invisible
    assert all(j["id"] for j in after["recent_jobs"])
    other_job = db.query(Job).filter(Job.tenant_id == other_tenant_id).first()
    assert client.post(f"/api/v1/system/jobs/{other_job.id}/retry", headers=admin_headers).status_code == 404


def test_new_endpoints_return_timezone_explicit_timestamps(client, operator_headers):
    s = client.post("/api/v1/copilot/sessions", json={"message": "Which approvals are pending?"}, headers=operator_headers).json()
    session = client.get(f"/api/v1/copilot/sessions/{s['id']}", headers=operator_headers).json()
    stamps = [session["created_at"], session["updated_at"], *(m["created_at"] for m in session["messages"])]
    assert all(re.search(r"(Z|[+-]\d\d:\d\d)$", t) for t in stamps), stamps
    batches = client.get("/api/v1/batches", headers=operator_headers).json()["items"]
    assert all(b["created_at"].endswith("Z") for b in batches)


def test_source_files_contain_no_double_encoded_utf8():
    root = Path(__file__).resolve().parents[2] / "app"
    pattern = re.compile("[\u00e2\u00c2\u00c3][\u0080-\u2122]")  # e.g. "â€”" for an em dash, "â†’" for an arrow
    bad = [f"{p.relative_to(root)}: {m.group(0)!r}" for p in root.rglob("*.py") for m in pattern.finditer(p.read_text("utf-8"))]
    assert not bad, bad
