"""Operational CLI: `python -m app.cli <command>`.

  init-db        create tables (SQLite) or print the Alembic command (PostgreSQL)
  seed           seed catalog + demo tenant and print demo credentials
  run-workflow   start a workflow for the demo tenant and wait for it
  evaluate       run synthetic evaluations for one or all agents
  maintenance    run the periodic maintenance job once
  serve          run the API with uvicorn (development)
"""

from __future__ import annotations

import argparse
import json
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging


def _bootstrap() -> None:
    import app.tools.catalog  # noqa: F401
    from app.agents.registry import agent_registry
    from app.db.session import create_all, session_scope
    from app.seed.catalog import sync_catalog

    if get_settings().is_sqlite:
        create_all()
    agent_registry.load_builtin()
    with session_scope() as db:
        sync_catalog(db)


def cmd_init_db(_: argparse.Namespace) -> None:
    s = get_settings()
    if s.is_sqlite:
        _bootstrap()
        print(f"SQLite schema created at {s.database_url}")
    else:
        print("PostgreSQL detected. Run: alembic upgrade head")


def cmd_seed(_: argparse.Namespace) -> None:
    import time

    from sqlalchemy.exc import OperationalError

    from app.db.session import reset_engine, session_scope
    from app.evaluation.harness import ensure_datasets
    from app.seed.demo import DEMO_TENANT_SLUG, DEMO_USERS, seed_demo

    # Seeding is idempotent, so a connection dropped mid-way (serverless Postgres such as Neon
    # suspending, or a flaky long-distance link) is retried on a fresh connection pool.
    for attempt in range(3):
        try:
            _bootstrap()
            with session_scope() as db:
                tenant = seed_demo(db)
                ensure_datasets(db)
            break
        except OperationalError as exc:
            if attempt == 2:
                raise
            print(f"database connection lost while seeding ({str(exc).splitlines()[0][:120]}); retrying...", flush=True)
            reset_engine(get_settings().database_url)
            time.sleep(3)
    print(f"Seeded demo tenant '{DEMO_TENANT_SLUG}' ({tenant.id})")
    custom = bool(get_settings().demo_password)
    print("Demo accounts" + (" (password: the DEMO_PASSWORD you configured):" if custom else " (local development only):"))
    for u in DEMO_USERS:
        print(f"  {u['email']:32s} role={u['roles'][0]:17s}" + ("" if custom else " password=OpsPilot-Demo-2026!"))


def cmd_run_workflow(args: argparse.Namespace) -> None:
    _bootstrap()
    from sqlalchemy import select

    from app.db.models import Tenant, WorkflowRun
    from app.db.session import session_scope
    from app.orchestration.engine import execute_run, start_run
    from app.seed.demo import DEMO_TENANT_SLUG

    payload = json.loads(args.input) if args.input else {}
    with session_scope() as db:
        tenant = db.execute(select(Tenant).where(Tenant.slug == (args.tenant or DEMO_TENANT_SLUG))).scalar_one()
        run = start_run(db, tenant_id=str(tenant.id), workflow_key=args.workflow, input=payload, actor_id="cli", enqueue=False)
        run_id = str(run.id)
    execute_run(run_id, worker_id="cli")
    with session_scope() as db:
        run = db.get(WorkflowRun, run.id)
        assert run is not None
        print(json.dumps({"run_id": run_id, "status": run.status, "steps": run.step_count, "cost_usd": run.cost_usd, "minutes_saved": run.estimated_minutes_saved, "output": run.output, "error": run.error}, indent=2, default=str))


def cmd_evaluate(args: argparse.Namespace) -> None:
    _bootstrap()
    from sqlalchemy import select

    from app.agents.registry import agent_registry
    from app.db.models import Tenant
    from app.db.session import session_scope
    from app.evaluation.harness import run_evaluation
    from app.seed.demo import DEMO_TENANT_SLUG, seed_demo

    keys = [args.agent] if args.agent else [s.key for s in agent_registry.specs()]
    rows = []
    with session_scope() as db:
        tenant = db.execute(select(Tenant).where(Tenant.slug == DEMO_TENANT_SLUG)).scalar_one_or_none() or seed_demo(db)
        db.commit()
        for k in keys:
            r = run_evaluation(db, tenant, k)
            rows.append((k, r.metrics))
            print(f"{'PASS' if r.passed else 'FAIL'} {k:28s} acc={r.metrics['accuracy']:.2f} cases={r.metrics['cases']} p50={r.metrics['p50_latency_ms']}ms intervention={r.metrics['human_intervention_rate']:.2f}")
    failed = [k for k, m in rows if m["passed"] < m["cases"]]
    if failed:
        print(f"\n{len(failed)} agent(s) with failing cases: {', '.join(failed)}")
        sys.exit(1)


def cmd_maintenance(_: argparse.Namespace) -> None:
    _bootstrap()
    from app.workers.queue import run_scheduled_maintenance

    print(json.dumps(run_scheduled_maintenance(), indent=2))


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


def main(argv: list[str] | None = None) -> None:
    configure_logging(get_settings().log_level, get_settings().log_json)
    p = argparse.ArgumentParser(prog="opspilot")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").set_defaults(fn=cmd_init_db)
    sub.add_parser("seed").set_defaults(fn=cmd_seed)
    rw = sub.add_parser("run-workflow")
    rw.add_argument("workflow")
    rw.add_argument("--input", default=None, help="JSON input")
    rw.add_argument("--tenant", default=None)
    rw.set_defaults(fn=cmd_run_workflow)
    ev = sub.add_parser("evaluate")
    ev.add_argument("--agent", default=None)
    ev.set_defaults(fn=cmd_evaluate)
    sub.add_parser("maintenance").set_defaults(fn=cmd_maintenance)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    sv.set_defaults(fn=cmd_serve)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
