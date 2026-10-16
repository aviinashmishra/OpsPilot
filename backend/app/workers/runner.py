"""Standalone worker process for the durable job queue.

    python -m app.workers.runner --concurrency 4 --name worker-1

Run one per CPU core / container replica; all of them share the database queue.
Ctrl+C (SIGINT) or SIGTERM stops claiming new jobs and lets running ones finish.
"""

from __future__ import annotations

import argparse
import os
import signal

from app.core.config import get_settings
from app.core.logging import configure_logging


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="opspilot-worker")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--name", default=None)
    parser.add_argument("--poll", type=float, default=0.5, help="seconds between queue polls when idle")
    parser.add_argument("--lease", type=int, default=None, help="job lease seconds (default JOB_LEASE_SECONDS); a dead worker's jobs return to the queue after this")
    args = parser.parse_args(argv)
    os.environ.setdefault("OPSPILOT_PROCESS_NAME", f"opspilot-worker:{args.name or os.getpid()}")
    s = get_settings()
    configure_logging(s.log_level, s.log_json)

    import app.tools.catalog  # noqa: F401 - registers tools
    from app.agents.registry import agent_registry
    from app.db.session import create_all

    if s.is_sqlite:
        create_all()
    agent_registry.load_builtin()

    from app.workers.pool import WorkerPool

    pool = WorkerPool(name=args.name, concurrency=args.concurrency, poll_interval=args.poll, lease_seconds=args.lease or s.job_lease_seconds)

    def _graceful(*_: object) -> None:
        pool._stop.set()  # noqa: SLF001 - signal handler

    signal.signal(signal.SIGINT, _graceful)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _graceful)
    pool.run_forever()


if __name__ == "__main__":
    main()
