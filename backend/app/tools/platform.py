"""Platform-internal adapter: tasks, knowledge retrieval, incidents, delegation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.db.models import Document, Incident, Task
from app.integrations.base import BaseAdapter, ConnectionTestResult, VerificationResult
from app.services.retrieval import search_documents


class PlatformAdapter(BaseAdapter):
    provider = "platform"
    mode = "platform"
    display_name = "OpsPilot platform"
    capabilities = ["tasks", "knowledge", "incidents", "workflows"]

    def __init__(self, db: Session, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, mode="platform", provider="platform", message="internal")

    def verify_action(self, method: str, request: dict[str, Any], external_ref: str | None) -> VerificationResult | None:
        if not external_ref:
            return VerificationResult(verified=False)
        try:
            ref = uuid.UUID(external_ref)
        except ValueError:
            return VerificationResult(verified=False)
        model = Task if method in {"create_task", "escalate_task"} else Incident
        exists = self.db.get(model, ref) is not None
        return VerificationResult(verified=True, exists=exists, external_ref=external_ref)

    # -- tasks ----------------------------------------------------------------
    def create_task(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        owner_user_id: str | None = None,
        owner_name: str | None = None,
        due_at: str | None = None,
        evidence_refs: list[str] | None = None,
        labels: list[str] | None = None,
        idempotency_key: str | None = None,
        source: str = "agent",
        source_run_id: str | None = None,
        created_by: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        if idempotency_key:
            existing = self.db.execute(
                select(Task).where(Task.tenant_id == self.tenant_id, Task.external_ref == idempotency_key)
            ).scalars().first()
            if existing:
                return {"id": str(existing.id), "task": _task_dict(existing), "duplicate_suppressed": True}
        due = None
        if due_at:
            try:
                due = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
                if due.tzinfo is None:
                    due = due.replace(tzinfo=UTC)
            except ValueError:
                due = None
        task = Task(
            tenant_id=self.tenant_id,
            title=title[:300],
            description=description,
            priority=priority,
            owner_user_id=uuid.UUID(owner_user_id) if owner_user_id else None,
            owner_name=owner_name,
            due_at=due,
            evidence_refs=evidence_refs or [],
            labels=labels or [],
            source=source,
            source_run_id=uuid.UUID(source_run_id) if source_run_id else None,
            external_ref=idempotency_key,
            created_by=created_by,
        )
        self.db.add(task)
        self.db.flush()
        return {"id": str(task.id), "task": _task_dict(task), "duplicate_suppressed": False}

    def escalate_task(self, task_id: str, level: int = 1, note: str = "", idempotency_key: str | None = None, **_: Any) -> dict[str, Any]:
        task = self.db.get(Task, uuid.UUID(task_id))
        if task is None or task.tenant_id != self.tenant_id:
            raise NotFound(f"Task {task_id} not found")
        if task.escalation_level >= level:
            return {"id": str(task.id), "task": _task_dict(task), "duplicate_suppressed": True}
        task.escalation_level = level
        labels = list(task.labels or [])
        if "escalated" not in labels:
            labels.append("escalated")
        task.labels = labels
        desc = (task.description or "") + f"\n\n[Escalation L{level}] {note}".rstrip()
        task.description = desc
        self.db.flush()
        return {"id": str(task.id), "task": _task_dict(task), "duplicate_suppressed": False}

    def list_tasks(self, status: str | None = None, overdue_only: bool = False, limit: int = 200, **_: Any) -> dict[str, Any]:
        stmt = select(Task).where(Task.tenant_id == self.tenant_id).order_by(Task.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(Task.status == status)
        rows = self.db.execute(stmt).scalars().all()
        now = datetime.now(UTC)
        items = []
        for t in rows:
            if overdue_only and not (t.due_at and _aware(t.due_at) < now and t.status not in {"done", "cancelled"}):
                continue
            items.append(_task_dict(t))
        return {"items": items, "count": len(items)}

    def workflow_usage(self, days: int = 90, **_: Any) -> dict[str, Any]:
        from datetime import timedelta

        from app.db.models import WorkflowRun

        since = datetime.now(UTC) - timedelta(days=days)
        rows = self.db.execute(select(WorkflowRun).where(WorkflowRun.tenant_id == self.tenant_id, WorkflowRun.created_at >= since)).scalars().all()
        agg: dict[str, dict[str, Any]] = {}
        for r in rows:
            a = agg.setdefault(r.workflow_key, {"workflow_key": r.workflow_key, "runs": 0, "succeeded": 0, "failed": 0, "ai_cost_usd": 0.0, "minutes_saved": 0.0})
            a["runs"] += 1
            a["ai_cost_usd"] = round(a["ai_cost_usd"] + r.cost_usd, 6)
            if r.status == "completed":
                a["succeeded"] += 1
                a["minutes_saved"] = round(a["minutes_saved"] + r.estimated_minutes_saved, 2)
            elif r.status in {"failed", "timed_out"}:
                a["failed"] += 1
        return {"items": sorted(agg.values(), key=lambda x: -x["runs"]), "days": days}

    # -- knowledge -------------------------------------------------------------
    def search_knowledge(self, query: str, collection: str | None = None, limit: int = 5, **_: Any) -> dict[str, Any]:
        hits = search_documents(self.db, str(self.tenant_id), query, collection=collection, limit=limit)
        return {"items": hits, "count": len(hits)}

    def list_documents(self, collection: str | None = None, limit: int = 100, **_: Any) -> dict[str, Any]:
        stmt = select(Document).where(Document.tenant_id == self.tenant_id).limit(limit)
        if collection:
            stmt = stmt.where(Document.collection == collection)
        rows = self.db.execute(stmt).scalars().all()
        return {
            "items": [
                {"id": str(d.id), "name": d.name, "collection": d.collection, "classification": d.classification, "scan_status": d.scan_status}
                for d in rows
            ]
        }

    # -- channel messages ---------------------------------------------------------
    def record_inbound_message(self, phone: str, text: str, message_id: str | None = None, idempotency_key: str | None = None, **_: Any) -> dict[str, Any]:
        from app.integrations.sandbox import SandboxStore

        store = SandboxStore(self.db, str(self.tenant_id))
        mid = message_id or (idempotency_key or "")[-24:] or None
        if mid and store.get("whatsapp_message", f"WAM-IN-{mid}"):
            return {"id": f"WAM-IN-{mid}", "duplicate_suppressed": True}
        rec = store.upsert("whatsapp_message", f"WAM-IN-{mid}" if mid else f"WAM-IN-{uuid.uuid4().hex[:10]}", {"phone": phone, "direction": "inbound", "text": text, "at": datetime.now(UTC).isoformat()})
        return {"id": rec["id"], "duplicate_suppressed": False}

    # -- incidents -------------------------------------------------------------
    def open_incident(self, title: str, severity: str = "medium", kind: str = "agent_finding", details: dict[str, Any] | None = None, source: str = "agent", run_id: str | None = None, idempotency_key: str | None = None, **_: Any) -> dict[str, Any]:
        if idempotency_key:
            existing = self.db.execute(
                select(Incident).where(Incident.tenant_id == self.tenant_id, Incident.status == "open", Incident.title == title)
            ).scalars().first()
            if existing:
                return {"id": str(existing.id), "duplicate_suppressed": True}
        inc = Incident(
            tenant_id=self.tenant_id,
            title=title[:300],
            severity=severity,
            kind=kind,
            source=source,
            details=details or {},
            run_id=uuid.UUID(run_id) if run_id else None,
        )
        self.db.add(inc)
        self.db.flush()
        return {"id": str(inc.id), "duplicate_suppressed": False}

    # -- delegation -------------------------------------------------------------
    def start_workflow(self, workflow_key: str, input: dict[str, Any], parent_run_id: str | None = None, depth: int = 0, actor_id: str = "system", idempotency_key: str | None = None, **_: Any) -> dict[str, Any]:
        from app.orchestration.engine import MAX_DELEGATION_DEPTH, start_run

        if depth >= MAX_DELEGATION_DEPTH:
            raise NotFound(f"Delegation depth {depth} exceeds the maximum of {MAX_DELEGATION_DEPTH}")
        run = start_run(
            self.db,
            tenant_id=str(self.tenant_id),
            workflow_key=workflow_key,
            input=input,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            parent_run_id=parent_run_id,
            depth=depth + 1,
            enqueue=True,
        )
        return {"id": str(run.id), "status": run.status, "duplicate_suppressed": False}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _task_dict(t: Task) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "title": t.title,
        "description": t.description,
        "status": t.status,
        "priority": t.priority,
        "owner_user_id": str(t.owner_user_id) if t.owner_user_id else None,
        "owner_name": t.owner_name,
        "due_at": t.due_at.isoformat() if t.due_at else None,
        "labels": t.labels,
        "evidence_refs": t.evidence_refs,
        "escalation_level": t.escalation_level,
        "source": t.source,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
