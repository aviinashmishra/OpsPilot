"""Engine/session management. Works with PostgreSQL and SQLite."""

from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _build_engine(url: str) -> Engine:
    s = get_settings()
    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool

        connect_args = {"check_same_thread": False}
        kwargs: dict = {"connect_args": connect_args, "echo": s.db_echo}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            # WAL + NORMAL never corrupts; it only defers the fsync, so commits (and lock hold times) are much shorter.
            cursor.execute("PRAGMA synchronous=NORMAL")
            # SQLite has one writer at a time; with several worker processes a short timeout turns contention into errors.
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        return engine
    # application_name shows which process holds a connection/lock in pg_stat_activity.
    app_name = (os.environ.get("OPSPILOT_PROCESS_NAME") or f"opspilot-{os.getpid()}")[:63]
    connect_args: dict = {"application_name": app_name}
    if s.is_transaction_pooler:
        # PgBouncer transaction mode: no startup "options", and server-side prepared statements
        # cannot follow a session across backends. Prefer Neon's direct endpoint for this app.
        connect_args["prepare_threshold"] = None
    else:
        connect_args["options"] = f"-c lock_timeout={int(s.db_lock_timeout_ms)} -c idle_in_transaction_session_timeout={int(s.db_idle_in_transaction_timeout_ms)}"
    return create_engine(url, pool_pre_ping=True, pool_size=s.db_pool_size, max_overflow=10, pool_recycle=s.db_pool_recycle_seconds, echo=s.db_echo, connect_args=connect_args)


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = _build_engine(get_settings().database_url)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, class_=Session)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def reset_engine(url: str | None = None) -> None:
    """Rebuild the engine (used by tests / after settings changes)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    if url:
        _engine = _build_engine(url)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, class_=Session)


def set_tenant_context(session: Session, tenant_id: str | None) -> None:
    """On PostgreSQL, set the RLS session variable so DB policies enforce tenant isolation."""
    if tenant_id and session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": str(tenant_id)})


def get_db() -> Generator[Session, None, None]:
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope(tenant_id: str | None = None) -> Iterator[Session]:
    db = get_sessionmaker()()
    try:
        set_tenant_context(db, tenant_id)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_all() -> None:
    """Create tables directly (used for SQLite dev/test; production uses Alembic)."""
    from app.db import models  # noqa: F401
    from app.db.base import Base

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "sqlite":
        _upgrade_sqlite_dev_schema(engine)


def _upgrade_sqlite_dev_schema(engine: Engine) -> None:
    """create_all never alters existing tables, so a dev SQLite file from an older version would
    miss newer columns ("no such column"). Add them in place. New columns are nullable, so this
    is safe; production PostgreSQL always uses the Alembic migrations instead."""
    from sqlalchemy import inspect

    from app.db.base import Base

    insp = inspect(engine)
    added: list[str] = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                if not col.nullable and col.server_default is None:
                    raise RuntimeError(f"Dev database is missing NOT NULL column {table.name}.{col.name}; delete the SQLite file and re-run seed")
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(dialect=engine.dialect)}'))
                added.append(f"{table.name}.{col.name}")
        if "audit_events.seq" in added:
            # Older files: unique chain position (SQLite can't add a constraint in place) and the new
            # content hashes, so the sealer can chain existing events.
            conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_events_seq ON audit_events (tenant_id, seq)'))
    if "audit_events.seq" in added:
        from app.db.models import AuditEvent
        from app.services.audit import _event_hash

        with Session(bind=engine) as s:
            for evt in s.query(AuditEvent).yield_per(1000):
                evt.hash = _event_hash(evt)
                evt.prev_hash = None
            s.commit()
    if added:
        import logging

        logging.getLogger("opspilot.db").warning("sqlite dev schema upgraded: added %s", ", ".join(added))
