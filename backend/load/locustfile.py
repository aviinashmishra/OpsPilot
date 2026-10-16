"""Load test: event ingestion + run polling + dashboard reads.

    pip install locust==2.31.5
    locust -f load/locustfile.py --host http://localhost:8000 -u 50 -r 5 --run-time 5m

Uses the seeded demo tenant and the sandbox adapters/mock LLM, so no external calls are made.
Watch: p95 of POST /events (dispatch only), workflow completion rate, and
`tool_executions.response.duplicate_suppressed` (must absorb all retried duplicates).
"""

from __future__ import annotations

import random
import uuid

from locust import HttpUser, between, task

LEAD = {"name": "Load Test", "company": "Globex", "title": "VP Operations", "industry": "logistics", "company_size": 900, "budget": 80000, "timeline": "this quarter", "message": "We need to automate warehouse exception handling."}


class OperatorUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        r = self.client.post("/api/v1/auth/login", json={"tenant": "acme-demo", "email": "ops@acme-demo.test", "password": "OpsPilot-Demo-2026!"})
        r.raise_for_status()
        self.headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        self.runs: list[str] = []

    @task(5)
    def ingest_lead(self) -> None:
        ext = uuid.uuid4().hex
        payload = {"source": "load", "event_type": "lead.created", "external_id": ext, "payload": {"lead": {**LEAD, "email": f"{ext[:8]}@load.test"}}}
        with self.client.post("/api/v1/events", json=payload, headers=self.headers, name="POST /events", catch_response=True) as r:
            if r.status_code == 202 and r.json().get("workflow_run_id"):
                self.runs.append(r.json()["workflow_run_id"])
            else:
                r.failure(f"unexpected {r.status_code}")
        if random.random() < 0.1:  # replay the same event: must be a no-op duplicate
            self.client.post("/api/v1/events", json=payload, headers=self.headers, name="POST /events (duplicate)")

    @task(3)
    def poll_run(self) -> None:
        if self.runs:
            self.client.get(f"/api/v1/workflows/{random.choice(self.runs[-20:])}", headers=self.headers, name="GET /workflows/{id}")

    @task(2)
    def dashboard(self) -> None:
        self.client.get("/api/v1/reports/overview?days=7", headers=self.headers, name="GET /reports/overview")
        self.client.get("/api/v1/approvals?status=pending&limit=20", headers=self.headers, name="GET /approvals")

    @task(1)
    def support_query(self) -> None:
        self.client.post("/api/v1/agents/customer_support/run", json={"input": {"message": "How long does standard shipping take?", "customer_id": "C-2001"}, "mode": "direct"}, headers=self.headers, name="POST /agents/customer_support/run")
