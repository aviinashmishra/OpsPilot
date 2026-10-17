"""FastAPI application entrypoint."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from app import __version__
from app.core.config import get_settings
from app.core.errors import OpsPilotError
from app.core.logging import configure_logging, correlation_id_var, get_logger
from app.core.telemetry import HTTP_LATENCY, HTTP_REQUESTS, metrics_payload, setup_tracing
from app.db.session import get_engine

log = get_logger("api")


def _bootstrap() -> None:
    """Ensure schema + catalog exist. SQLite dev databases are created directly;
    PostgreSQL deployments are expected to run `alembic upgrade head` first."""
    from app.agents.registry import agent_registry
    from app.db.session import create_all, session_scope
    from app.seed.catalog import sync_catalog

    s = get_settings()
    if s.is_sqlite:
        create_all()
    agent_registry.load_builtin()
    import app.tools.catalog  # noqa: F401 - registers tools

    with session_scope() as db:
        sync_catalog(db)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    for problem in s.validate_for_environment():
        log.warning("config.problem", problem=problem)
    _bootstrap()
    if s.worker_mode in {"thread", "db"}:
        from app.workers.queue import start_local_scheduler

        start_local_scheduler(60)
    if s.worker_mode == "thread":
        from app.workers.pool import start_local_pool

        start_local_pool(s.worker_concurrency)
    log.info("startup.complete", version=__version__, env=s.app_env, llm=s.effective_llm_provider, worker=s.worker_mode)
    manager = getattr(app.state, "mcp_session_manager", None)
    if manager is not None:
        async with manager.run():
            yield
    else:
        yield
    if s.worker_mode == "thread":
        from app.workers.pool import stop_local_pool

        stop_local_pool()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="OpsPilot AI API",
        version=__version__,
        description=(
            "Multi-tenant AI workforce platform: 25 specialist agents, a durable workflow orchestrator, "
            "policy-gated actions with human approval, and full audit. All endpoints except health and "
            "signed webhooks require a bearer token (OIDC or local issuer) or an X-API-Key."
        ),
        lifespan=lifespan,
        openapi_tags=[
            {"name": "auth"}, {"name": "events"}, {"name": "workflows"}, {"name": "agents"}, {"name": "tasks"},
            {"name": "approvals"}, {"name": "integrations"}, {"name": "reports"}, {"name": "documents"},
            {"name": "evaluations"}, {"name": "admin"}, {"name": "health"},
        ],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-API-Key", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID"],
    )

    @app.middleware("http")
    async def correlation_and_metrics(request: Request, call_next):  # type: ignore[no-untyped-def]
        cid = request.headers.get("X-Correlation-ID") or uuid.uuid4().hex
        if len(cid) > 64 or not all(ch.isalnum() or ch in "-_" for ch in cid):
            cid = uuid.uuid4().hex
        correlation_id_var.set(cid)
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, path).observe(time.perf_counter() - started)
        response.headers["X-Correlation-ID"] = cid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(OpsPilotError)
    async def opspilot_error(_request: Request, exc: OpsPilotError) -> JSONResponse:
        status = exc.status_code if exc.status_code >= 400 else 400
        headers = {"Retry-After": "30"} if status == 429 else None
        return JSONResponse(status_code=status, content={"error": {**exc.to_dict(), "correlation_id": correlation_id_var.get()}}, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()[:20]]
        return JSONResponse(status_code=422, content={"error": {"code": "validation_failed", "message": "Request validation failed", "details": {"errors": errors}, "correlation_id": correlation_id_var.get()}})

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", error_type=type(exc).__name__)
        # Never leak internals to clients.
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "An unexpected error occurred", "details": {}, "correlation_id": correlation_id_var.get()}})

    from app.api.routes import (
        admin,
        agents,
        approvals,
        auth,
        copilot,
        documents,
        evaluations,
        events,
        integrations,
        onboarding,
        reports,
        tasks,
        tools_admin,
        workflows,
    )

    for r in (auth.router, events.router, workflows.router, agents.router, tasks.router, approvals.router, integrations.router, reports.router, documents.router, evaluations.router, admin.router, copilot.router, tools_admin.router, onboarding.router):
        app.include_router(r, prefix=s.api_prefix)

    from app.mcp_server import mount_mcp

    mount_mcp(app)

    @app.get(f"{s.api_prefix}/health", tags=["health"], summary="Public status for the dashboard (reachable through the same-origin proxy)")
    def api_health() -> dict[str, Any]:
        db_ok = True
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            db_ok = False
        cfg = get_settings()
        from app.llm.gateway import get_gateway

        ai = get_gateway().ai_status()
        return {"status": "ok" if db_ok else "degraded", "version": __version__, "database": "ok" if db_ok else "unreachable", "llm_provider": cfg.effective_llm_provider, "ai_available": ai["available"], "ai_next_available_at": ai["next_available_at"], "signup_enabled": cfg.allow_signup and cfg.allow_password_login, "worker_mode": cfg.worker_mode, "environment": cfg.app_env}

    @app.get("/health/live", tags=["health"], summary="Liveness probe")
    def live() -> dict[str, Any]:
        return {"status": "ok", "version": __version__}

    @app.get("/health/ready", tags=["health"], summary="Readiness probe (database + configuration)")
    def ready() -> JSONResponse:
        checks: dict[str, Any] = {}
        ok = True
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:  # noqa: BLE001
            ok = False
            checks["database"] = f"error: {type(exc).__name__}"
        problems = get_settings().validate_for_environment()
        checks["config_warnings"] = problems
        checks["llm_provider"] = get_settings().effective_llm_provider
        checks["worker_mode"] = get_settings().worker_mode
        if get_settings().is_production and problems:
            ok = False
        return JSONResponse(status_code=200 if ok else 503, content={"status": "ready" if ok else "not_ready", "checks": checks})

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        if not get_settings().metrics_enabled:
            return Response(status_code=404)
        body, ctype = metrics_payload()
        return Response(content=body, media_type=ctype)

    setup_tracing(app)
    return app


app = create_app()
