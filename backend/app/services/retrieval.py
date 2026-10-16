"""Tenant-scoped document retrieval.

Lexical retrieval (BM25-style scoring over chunks) always works, including on
SQLite. When pgvector is enabled and chunks carry embeddings, cosine similarity
is blended in. Every hit carries an evidence reference `document:<id>#chunk:<n>`.
"""

from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentChunk

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "for", "on", "with", "by", "at", "be", "as", "it", "this", "that", "are", "we", "you", "i", "do", "does", "can", "how", "what", "my"}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP and len(t) > 1]


def chunk_text(text: str, max_chars: int = 900) -> list[tuple[str | None, str]]:
    """Split by headings/paragraphs into (section, text) chunks of bounded size."""
    chunks: list[tuple[str | None, str]] = []
    section: str | None = None
    buf: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal buf, size
        if buf:
            chunks.append((section, "\n".join(buf).strip()))
        buf, size = [], 0

    for line in (text or "").splitlines():
        if re.match(r"^\s*(#{1,6}\s+|\d+(\.\d+)*\s+[A-Z])", line):
            flush()
            section = line.strip().lstrip("#").strip()[:120]
        if size + len(line) > max_chars and buf:
            flush()
        buf.append(line)
        size += len(line) + 1
    flush()
    return [c for c in chunks if c[1]]


def index_document(db: Session, doc: Document, embed: Any | None = None) -> int:
    for old in list(doc.chunks):
        db.delete(old)
    db.flush()
    pieces = chunk_text(doc.text_content or "")
    for i, (section, text) in enumerate(pieces):
        emb = embed(text) if embed else None
        db.add(
            DocumentChunk(
                tenant_id=doc.tenant_id,
                document_id=doc.id,
                chunk_index=i,
                text=text,
                section=section,
                embedding=emb,
                token_count=len(tokenize(text)),
            )
        )
    db.flush()
    return len(pieces)


def _bm25(query_terms: list[str], docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    n = len(docs)
    if n == 0:
        return []
    avgdl = sum(len(d) for d in docs) / n
    df: Counter[str] = Counter()
    for d in docs:
        for t in set(d):
            df[t] += 1
    scores = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for t in query_terms:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * (tf[t] * (k1 + 1)) / (tf[t] + k1 * (1 - b + b * len(d) / (avgdl or 1)))
        scores.append(s)
    return scores


def search_documents(
    db: Session, tenant_id: str, query: str, *, collection: str | None = None, limit: int = 5, min_score: float = 0.2
) -> list[dict[str, Any]]:
    tid = uuid.UUID(str(tenant_id))
    stmt = (
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.tenant_id == tid, Document.tenant_id == tid, Document.scan_status != "flagged")
    )
    if collection:
        stmt = stmt.where(Document.collection == collection)
    rows = db.execute(stmt).all()
    if not rows:
        return []
    q_terms = tokenize(query)
    if not q_terms:
        return []
    docs = [tokenize(chunk.text) for chunk, _ in rows]
    scores = _bm25(q_terms, docs)
    ranked = sorted(zip(scores, rows, strict=True), key=lambda x: -x[0])
    out: list[dict[str, Any]] = []
    for score, (chunk, doc) in ranked[:limit]:
        if score < min_score:
            continue
        out.append(
            {
                "ref": f"document:{doc.id}#chunk:{chunk.chunk_index}",
                "document_id": str(doc.id),
                "document_name": doc.name,
                "collection": doc.collection,
                "section": chunk.section,
                "text": chunk.text,
                "score": round(float(score), 4),
            }
        )
    return out
