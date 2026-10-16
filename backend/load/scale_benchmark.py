"""Scale benchmark: real worker processes against an isolated database.

    cd backend
    .venv\\Scripts\\python -m load.scale_benchmark --items 300 --workers 1,4

Phases
  1. Throughput: one bulk run of N lead-qualification items, drained by W worker
     processes (WORKER_MODE=db, separate OS processes), for each W.
  2. Ingestion burst: concurrent POST /events with 20% exact duplicates.
  3. Crash recovery: kill a worker process hard mid-batch; the batch must still
     finish with every item processed exactly once.
Every phase verifies exactly-once processing straight from the database.
Uses the mock LLM and sandbox adapters (no network, no real side effects).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
PY = sys.executable


def env_for(db_url: str) -> dict[str, str]:
    e = dict(os.environ)
    e.update({"DATABASE_URL": db_url, "WORKER_MODE": "db", "LLM_PROVIDER": "mock", "LOG_LEVEL": "WARNING", "RATE_LIMIT_PER_MINUTE": "1000000", "JOB_LEASE_SECONDS": "6", "BATCH_ITEM_STALE_SECONDS": "6", "PYTHONUTF8": "1"})
    return e


def start(args: list[str], env: dict[str, str], log: Path) -> subprocess.Popen:
    f = open(log, "w", encoding="utf-8")  # noqa: SIM115 - kept open for the child's lifetime
    return subprocess.Popen([PY, *args], cwd=BACKEND, env=env, stdout=f, stderr=subprocess.STDOUT)


def wait_http(url: str, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"{url} not healthy")


def items(n: int, tag: str) -> list[dict]:
    return [{"lead": {"name": f"Load {tag} {i}", "email": f"load-{tag}-{i}@example.test", "company": f"Company {i % 37}", "title": "VP Operations" if i % 3 else "Analyst", "industry": "logistics", "company_size": 50 + i, "budget": 5000 + i * 100, "timeline": "this quarter", "message": "We need to automate operations."}} for i in range(n)]


def run_batch(api: str, headers: dict, n: int, tag: str, timeout: float = 300, on_progress=None) -> dict:
    r = httpx.post(f"{api}/agents/lead_qualification/batches", json={"items": items(n, tag), "name": f"bench-{tag}", "execute_actions": True}, headers=headers, timeout=120)
    r.raise_for_status()
    bid = r.json()["id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        b = httpx.get(f"{api}/batches/{bid}?limit=1", headers=headers, timeout=30).json()
        if on_progress:
            on_progress(b)
        if b["status"] != "running":
            return {**b, "wall_seconds": round(time.time() - t0, 2)}
        time.sleep(0.5)
    raise RuntimeError("batch timed out")


def q(db_url: str, sql: str, **params) -> list[tuple]:
    from sqlalchemy import create_engine, text

    eng = create_engine(db_url)
    try:
        with eng.connect() as c:
            return [tuple(r) for r in c.execute(text(sql), params).all()]
    finally:
        eng.dispose()


def verify_exactly_once(db_url: str, batch_id: str) -> dict:
    bid = str(uuid.UUID(batch_id))
    corr = q(db_url, "select correlation_id from agent_batches where cast(id as varchar(36)) = :b", b=bid)[0][0]
    statuses = dict(q(db_url, "select status, count(*) from agent_batch_items where cast(batch_id as varchar(36)) = :b group by status", b=bid))
    # Every agent run of the batch shares its correlation id. An item re-run after a worker crash adds an agent run
    # (compute is at-least-once) but must not add side effects (actions are exactly-once per item).
    agent_runs = q(db_url, "select count(*) from agent_runs where correlation_id = :c", c=corr)[0][0]
    effects = q(db_url, "select count(*), count(distinct idempotency_key) from tool_executions where correlation_id = :c and side_effect = :t and status in ('succeeded','verified','reconciled')", c=corr, t=True)[0]
    per_lead: dict[str, int] = {}
    for (req,) in q(db_url, "select request from tool_executions where correlation_id = :c and tool_key = 'crm.upsert_lead' and status in ('succeeded','verified','reconciled')", c=corr):
        email = (json.loads(req) if isinstance(req, str) else req).get("lead", {}).get("email", "?")
        per_lead[email] = per_lead.get(email, 0) + 1
    return {
        "item_statuses": statuses, "agent_runs": agent_runs, "side_effects": effects[0], "distinct_side_effect_keys": effects[1],
        "leads_created": len(per_lead), "max_creates_for_one_lead": max(per_lead.values(), default=0),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", type=int, default=300)
    ap.add_argument("--workers", default="1,4")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--events", type=int, default=400)
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--api-workers", type=int, default=1, help="uvicorn worker processes for the API")
    ap.add_argument("--database-url", default=None, help="EMPTY PostgreSQL database (default: a fresh SQLite file)")
    ap.add_argument("--out", default="scale_results.json")
    ap.add_argument("--check", action="store_true", help="exit 1 unless every phase completed with no lost item and no duplicate side effect")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="opspilot-bench-"))
    db_url = args.database_url or f"sqlite:///{(tmp / 'bench.db').as_posix()}"
    env = env_for(db_url)
    api = f"http://127.0.0.1:{args.port}/api/v1"
    dialect = "postgresql" if db_url.startswith("postgresql") else "sqlite (WAL)"
    results: dict = {"items": args.items, "per_worker_concurrency": args.concurrency, "api_processes": args.api_workers, "database": dialect, "cpu_count": os.cpu_count()}
    procs: list[subprocess.Popen] = []
    try:
        if dialect == "postgresql":
            subprocess.run([PY, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True, capture_output=True)
        subprocess.run([PY, "-m", "app.cli", "seed"], cwd=BACKEND, env=env, check=True, capture_output=True)
        procs.append(start(["-m", "uvicorn", "app.main:app", "--port", str(args.port), "--workers", str(args.api_workers)], {**env, "OPSPILOT_PROCESS_NAME": "opspilot-api"}, tmp / "api.log"))
        wait_http(f"{api}/health")
        tok = httpx.post(f"{api}/auth/login", json={"tenant": "acme-demo", "email": "ops@acme-demo.test", "password": "OpsPilot-Demo-2026!"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {tok}"}

        # Phase 1 - throughput vs worker processes
        results["throughput"] = []
        for w in [int(x) for x in args.workers.split(",")]:
            workers = [start(["-m", "app.workers.runner", "--concurrency", str(args.concurrency), "--name", f"bench-w{w}-{i}", "--poll", "0.2"], env, tmp / f"w{w}-{i}.log") for i in range(w)]
            procs.extend(workers)  # killed in `finally` even if this phase fails
            time.sleep(2)
            b = run_batch(api, headers, args.items, f"w{w}")
            check = verify_exactly_once(db_url, b["id"])
            for p in workers:
                p.terminate()
            for p in workers:
                p.wait(20)
            row = {"worker_processes": w, "total_concurrency": w * args.concurrency, "items": b["total"], "completed": b["succeeded"] + b["needs_review"], "failed": b["failed"], "wall_seconds": b["wall_seconds"], "items_per_second": round(b["total"] / b["wall_seconds"], 2), **check}
            results["throughput"].append(row)
            print(json.dumps(row), flush=True)

        # Phase 2 - ingestion burst with duplicates (API only; dispatch is queued, not executed inline)
        unique = int(args.events * 0.8)
        if args.events <= 0:
            raise SystemExit(0)
        payloads = [{"source": "bench", "event_type": "support.message_received", "external_id": f"evt-{i}", "payload": {"message": "How long does standard shipping take?", "customer_id": "C-2001"}} for i in range(unique)]
        payloads += payloads[: args.events - unique]
        lat: list[float] = []
        # One pooled client: creating a client per request costs more CPU than the request itself.
        http = httpx.Client(timeout=60, limits=httpx.Limits(max_connections=64, max_keepalive_connections=64))

        def post(p: dict) -> tuple[int, bool]:
            t = time.perf_counter()
            r = http.post(f"{api}/events", json=p, headers=headers)
            lat.append((time.perf_counter() - t) * 1000)
            return r.status_code, r.status_code == 202 and bool(r.json().get("duplicate"))

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=32) as pool:
            out = list(pool.map(post, payloads))
        wall = time.time() - t0
        runs = q(db_url, "select count(*) from workflow_runs where workflow_key = 'customer_query' and idempotency_key like 'event:%'")[0][0]
        lat.sort()
        results["ingestion"] = {"requests": len(payloads), "unique_events": unique, "status_codes": {str(c): sum(1 for s, _ in out if s == c) for c in {s for s, _ in out}}, "duplicates_detected": sum(1 for _, d in out if d), "workflow_runs_created": runs, "requests_per_second": round(len(payloads) / wall, 1), "p50_ms": round(statistics.median(lat), 1), "p95_ms": round(lat[int(len(lat) * 0.95) - 1], 1), "max_ms": round(lat[-1], 1)}
        print(json.dumps(results["ingestion"]), flush=True)

        # Phase 3 - crash recovery: kill -9 one of three workers mid-batch
        workers = [start(["-m", "app.workers.runner", "--concurrency", str(args.concurrency), "--name", f"crash-{i}", "--poll", "0.2", "--lease", "6"], env, tmp / f"crash-{i}.log") for i in range(3)]
        procs.extend(workers)
        time.sleep(2)
        killed = {"done": False}

        def maybe_kill(b: dict) -> None:
            if not killed["done"] and b["processed"] >= b["total"] * 0.3:
                workers[0].kill()  # hard kill: no graceful shutdown, leases left dangling
                killed["done"] = True
                killed["at_processed"] = b["processed"]

        b = run_batch(api, headers, max(60, args.items // 2), "crash", on_progress=maybe_kill)
        check = verify_exactly_once(db_url, b["id"])
        for p in workers[1:]:
            p.terminate()
        results["crash_recovery"] = {"items": b["total"], "worker_killed_at_processed": killed.get("at_processed"), "completed": b["succeeded"] + b["needs_review"], "failed": b["failed"], "status": b["status"], "wall_seconds": b["wall_seconds"], **check}
        print(json.dumps(results["crash_recovery"]), flush=True)
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        results["problems"] = problems(results)
        out_file = BACKEND / "load" / args.out
        out_file.write_text(json.dumps(results, indent=2), "utf-8")
        print(f"\nresults written to {out_file} (logs in {tmp})")
        print("PROBLEMS:", results["problems"] or "none", flush=True)
    if args.check and results["problems"]:
        sys.exit(1)


def problems(results: dict) -> list[str]:
    """Correctness invariants; throughput numbers are reported, never asserted."""
    out: list[str] = []
    phases = [*results.get("throughput", []), *([results["crash_recovery"]] if "crash_recovery" in results else [])]
    if not phases:
        out.append("no phase completed")
    for p in phases:
        name = f"{p.get('worker_processes', 'crash')}-worker" if "worker_processes" in p else "crash-recovery"
        if p["completed"] + p["failed"] != p["items"]:
            out.append(f"{name}: {p['items'] - p['completed'] - p['failed']} items lost")
        if p["failed"]:
            out.append(f"{name}: {p['failed']} items failed")
        if p["side_effects"] != p["distinct_side_effect_keys"] or p["max_creates_for_one_lead"] > 1:
            out.append(f"{name}: duplicate side effects")
    ing = results.get("ingestion")
    if ing:
        if ing["workflow_runs_created"] != ing["unique_events"]:
            out.append(f"ingestion: {ing['workflow_runs_created']} runs for {ing['unique_events']} unique events")
        if any(code != "202" for code in ing["status_codes"]):
            out.append(f"ingestion: non-202 responses {ing['status_codes']}")
    return out


if __name__ == "__main__":
    main()
