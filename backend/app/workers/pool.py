"""Worker pool that drains the durable job queue.

Used two ways:
* in-process (WORKER_MODE=thread): started by the API on startup;
* standalone (WORKER_MODE=db): ``python -m app.workers.runner --concurrency 4``,
  run as many processes / machines as you like against the same database.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models import WorkerHeartbeat
from app.db.session import get_sessionmaker
from app.workers import jobs as jq

log = get_logger("worker")


class WorkerPool:
    def __init__(self, name: str | None = None, concurrency: int = 4, poll_interval: float = 0.5, lease_seconds: int = jq.DEFAULT_LEASE_SECONDS) -> None:
        self.name = name or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:4]}"
        self.concurrency = max(1, concurrency)
        self.poll_interval = poll_interval
        self.lease_seconds = lease_seconds
        self._executor = ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix=f"opspilot-{self.name}")
        self._active: dict[uuid.UUID, Future] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.processed = 0
        self.failed = 0
        self._last_reap = 0.0
        self._last_renew = 0.0
        self._last_beat = 0.0

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> WorkerPool:
        self._thread = threading.Thread(target=self._loop, name=f"opspilot-pool-{self.name}", daemon=True)
        self._thread.start()
        log.info("worker.started", worker=self.name, concurrency=self.concurrency)
        return self

    def wake(self) -> None:
        self._wake.set()

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)
        self._executor.shutdown(wait=True, cancel_futures=False)
        self._beat(status="stopped")

    def run_forever(self) -> None:
        self.start()
        try:
            while not self._stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def idle(self) -> bool:
        return self.active_count == 0

    # -- main loop ---------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:  # noqa: BLE001 - the pool must survive transient DB errors
                log.exception("worker.tick_failed", worker=self.name)
                time.sleep(1.0)
            self._wake.wait(self.poll_interval)
            self._wake.clear()

    def _tick(self) -> None:
        now = time.monotonic()
        Session = get_sessionmaker()
        with self._lock:
            done = [jid for jid, f in self._active.items() if f.done()]
            for jid in done:
                self._active.pop(jid, None)
            active_ids = list(self._active)
        if now - self._last_renew > self.lease_seconds / 3 and active_ids:
            with Session() as db:
                jq.renew_leases(db, self.name, active_ids, self.lease_seconds)
            self._last_renew = now
        if now - self._last_reap > 15:
            with Session() as db:
                jq.reap_expired_leases(db)
            self._last_reap = now
        if now - self._last_beat > 5:
            self._beat()
            self._last_beat = now
        free = self.concurrency - len(active_ids)
        if free <= 0 or self._stop.is_set():
            return
        with Session() as db:
            claimed = jq.claim_jobs(db, self.name, free, self.lease_seconds)
            claimed_ids = [(j.id, j.kind, dict(j.payload or {})) for j in claimed]
        for jid, kind, payload in claimed_ids:
            fut = self._executor.submit(self._run_job, jid, kind, payload)
            with self._lock:
                self._active[jid] = fut

    def _run_job(self, job_id: uuid.UUID, kind: str, payload: dict) -> None:
        Session = get_sessionmaker()
        started = time.perf_counter()
        try:
            fn = jq.get_handler(kind)
            result = fn(payload, self.name)
            with Session() as db:
                jq.complete_job(db, job_id, self.name, result if isinstance(result, dict) else None)
            self.processed += 1
            log.info("job.done", job=str(job_id), kind=kind, ms=int((time.perf_counter() - started) * 1000))
        except Exception as exc:  # noqa: BLE001
            self.failed += 1
            log.exception("job.failed", job=str(job_id), kind=kind)
            with Session() as db:
                jq.fail_job(db, job_id, self.name, f"{type(exc).__name__}: {exc}")
        finally:
            self._wake.set()

    def _beat(self, status: str = "running") -> None:
        try:
            with get_sessionmaker()() as db:
                hb = db.execute(select(WorkerHeartbeat).where(WorkerHeartbeat.name == self.name)).scalar_one_or_none()
                if hb is None:
                    hb = WorkerHeartbeat(name=self.name, hostname=socket.gethostname(), pid=os.getpid(), concurrency=self.concurrency)
                    db.add(hb)
                hb.active_jobs = self.active_count
                hb.processed = self.processed
                hb.failed = self.failed
                hb.status = status
                hb.last_seen_at = datetime.now(UTC)
                db.commit()
        except Exception:  # noqa: BLE001
            log.exception("worker.heartbeat_failed", worker=self.name)


_pool: WorkerPool | None = None


def get_local_pool() -> WorkerPool | None:
    return _pool


def start_local_pool(concurrency: int) -> WorkerPool:
    global _pool
    if _pool is None:
        from app.core.config import get_settings

        _pool = WorkerPool(name=f"api-{socket.gethostname()}-{os.getpid()}", concurrency=concurrency, lease_seconds=get_settings().job_lease_seconds).start()
    return _pool


def stop_local_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.stop()
        _pool = None
