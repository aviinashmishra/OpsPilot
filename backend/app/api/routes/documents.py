"""Documents: safe upload, scanning, indexing, retrieval."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.schemas import DocumentOut, DocumentTextIn
from app.api.serializers import document_out
from app.core.config import get_settings
from app.core.errors import NotFound, ValidationFailed
from app.db.models import Document
from app.db.session import get_db
from app.services.audit import record_audit
from app.services.documents import extract_text, scan_document
from app.services.retrieval import index_document, search_documents

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_TYPES = {"text/plain", "text/markdown", "text/csv", "application/json", "application/pdf"}


def _store(principal: Principal, data: bytes, name: str) -> str:
    s = get_settings()
    safe = "".join(ch for ch in Path(name).name if ch.isalnum() or ch in "._-")[:120] or "document"
    key = f"{principal.tenant.id}/{uuid.uuid4().hex}_{safe}"
    if s.document_storage_backend == "local":
        path = Path(s.document_storage_path) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return key


def _create(db: Session, principal: Principal, *, name: str, collection: str, content_type: str, data: bytes, text: str, classification: str, meta: dict) -> Document:
    findings = scan_document(text, data, content_type)
    doc = Document(
        tenant_id=principal.tenant.id, name=name[:300], collection=collection, content_type=content_type, storage_key=_store(principal, data, name),
        size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), classification=classification, text_content=text, meta=meta,
        uploaded_by=principal.actor_id, scan_status="flagged" if any(f["severity"] == "high" for f in findings) else "clean", scan_findings=findings,
    )
    db.add(doc)
    db.flush()
    chunks = index_document(db, doc)
    record_audit(db, tenant_id=principal.tenant.id, action="document.uploaded", resource_type="document", resource_id=str(doc.id), actor_id=principal.actor_id, details={"name": doc.name, "collection": collection, "chunks": chunks, "scan_status": doc.scan_status, "findings": len(findings)}, severity="warning" if doc.scan_status == "flagged" else "info")
    db.commit()
    db.refresh(doc)
    return doc


@router.get("", response_model=list[DocumentOut], summary="List documents")
def list_documents(collection: str | None = None, principal: Principal = Depends(require("documents:read")), db: Session = Depends(get_db)) -> list[DocumentOut]:
    stmt = select(Document).where(Document.tenant_id == principal.tenant.id)
    if collection:
        stmt = stmt.where(Document.collection == collection)
    return [document_out(d) for d in db.execute(stmt.order_by(Document.created_at.desc())).scalars().all()]


@router.post("/text", response_model=DocumentOut, status_code=201, summary="Add a text document to a collection")
def add_text(body: DocumentTextIn, principal: Principal = Depends(require("documents:write")), db: Session = Depends(get_db)) -> DocumentOut:
    doc = _create(db, principal, name=body.name, collection=body.collection, content_type="text/plain", data=body.text.encode("utf-8"), text=body.text, classification=body.classification, meta=body.meta)
    return document_out(doc)


@router.post("/upload", response_model=DocumentOut, status_code=201, summary="Upload a document file")
async def upload(
    file: UploadFile = File(...),
    collection: str = Form("kb"),
    classification: str = Form("internal"),
    principal: Principal = Depends(require("documents:write")),
    db: Session = Depends(get_db),
) -> DocumentOut:
    s = get_settings()
    data = await file.read(s.max_document_size_mb * 1024 * 1024 + 1)
    if len(data) > s.max_document_size_mb * 1024 * 1024:
        raise ValidationFailed(f"File exceeds {s.max_document_size_mb} MB")
    ctype = (file.content_type or "application/octet-stream").split(";")[0]
    if ctype not in ALLOWED_TYPES:
        raise ValidationFailed(f"Unsupported content type '{ctype}'", details={"allowed": sorted(ALLOWED_TYPES)})
    text = extract_text(data, ctype)
    doc = _create(db, principal, name=file.filename or "upload", collection=collection, content_type=ctype, data=data, text=text, classification=classification, meta={})
    return document_out(doc)


@router.get("/search", summary="Search authorized documents")
def search(q: str = Query(min_length=2), collection: str | None = None, limit: int = Query(5, ge=1, le=20), principal: Principal = Depends(require("documents:read")), db: Session = Depends(get_db)) -> dict:
    return {"items": search_documents(db, str(principal.tenant.id), q, collection=collection, limit=limit)}


@router.delete("/{document_id}", status_code=204, summary="Delete a document", response_class=Response)
def delete_document(document_id: str, principal: Principal = Depends(require("documents:write")), db: Session = Depends(get_db)) -> Response:
    doc = db.get(Document, uuid.UUID(document_id))
    if doc is None or doc.tenant_id != principal.tenant.id:
        raise NotFound("Document not found")
    db.delete(doc)
    record_audit(db, tenant_id=principal.tenant.id, action="document.deleted", resource_type="document", resource_id=document_id, actor_id=principal.actor_id)
    db.commit()
    return Response(status_code=204)
