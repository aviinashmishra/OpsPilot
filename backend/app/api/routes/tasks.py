"""Tasks board."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.schemas import Page, TaskIn, TaskOut, TaskUpdateIn
from app.api.serializers import task_out
from app.core.errors import NotFound, ValidationFailed
from app.db.models import Task, User
from app.db.session import get_db
from app.services.audit import record_audit

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _owner(db: Session, principal: Principal, owner_user_id: str | None) -> User | None:
    if not owner_user_id:
        return None
    try:
        user = db.get(User, uuid.UUID(owner_user_id))
    except ValueError as exc:
        raise ValidationFailed("owner_user_id must be a UUID") from exc
    if user is None or user.tenant_id != principal.tenant.id:
        raise ValidationFailed("Owner must be a user in your tenant")
    return user


@router.get("", response_model=Page[TaskOut], summary="List tasks")
def list_tasks(
    status: str | None = None,
    overdue: bool | None = None,
    owner_user_id: str | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require("tasks:read")),
    db: Session = Depends(get_db),
) -> Page[TaskOut]:
    stmt = select(Task).where(Task.tenant_id == principal.tenant.id)
    if status:
        stmt = stmt.where(Task.status.in_(status.split(",")))
    if owner_user_id:
        stmt = stmt.where(Task.owner_user_id == uuid.UUID(owner_user_id))
    if q:
        stmt = stmt.where(Task.title.contains(q))
    if overdue:
        stmt = stmt.where(Task.due_at < datetime.now(UTC), Task.status.notin_(["done", "cancelled"]))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Task.due_at.is_(None), Task.due_at.asc(), Task.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return Page(items=[task_out(t) for t in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=TaskOut, status_code=201, summary="Create a task")
def create_task(body: TaskIn, principal: Principal = Depends(require("tasks:write")), db: Session = Depends(get_db)) -> TaskOut:
    owner = _owner(db, principal, body.owner_user_id)
    t = Task(
        tenant_id=principal.tenant.id, title=body.title, description=body.description, priority=body.priority,
        owner_user_id=owner.id if owner else None, owner_name=owner.full_name if owner else body.owner_name,
        due_at=body.due_at, labels=body.labels, source="manual", created_by=principal.actor_id,
    )
    db.add(t)
    db.flush()
    record_audit(db, tenant_id=principal.tenant.id, action="task.created", resource_type="task", resource_id=str(t.id), actor_id=principal.actor_id, details={"title": t.title})
    db.commit()
    return task_out(t)


@router.patch("/{task_id}", response_model=TaskOut, summary="Update a task")
def update_task(task_id: str, body: TaskUpdateIn, principal: Principal = Depends(require("tasks:write")), db: Session = Depends(get_db)) -> TaskOut:
    t = db.get(Task, uuid.UUID(task_id))
    if t is None or t.tenant_id != principal.tenant.id:
        raise NotFound("Task not found")
    data = body.model_dump(exclude_unset=True)
    if "owner_user_id" in data:
        owner = _owner(db, principal, data.pop("owner_user_id"))
        t.owner_user_id = owner.id if owner else None
        if owner:
            t.owner_name = owner.full_name
    for k, v in data.items():
        setattr(t, k, v)
    if body.status == "done" and not t.completed_at:
        t.completed_at = datetime.now(UTC)
    db.flush()
    record_audit(db, tenant_id=principal.tenant.id, action="task.updated", resource_type="task", resource_id=str(t.id), actor_id=principal.actor_id, details={"changes": body.model_dump(exclude_unset=True, mode="json")})
    db.commit()
    return task_out(t)
