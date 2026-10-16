"""Per-tenant sliding-window rate limiter (Redis when available, in-memory otherwise)."""

from __future__ import annotations

import threading
import time
from collections import deque

from app.core.config import get_settings
from app.core.errors import RateLimited

_lock = threading.Lock()
_windows: dict[str, deque[float]] = {}
_redis = None


def _redis_client():  # type: ignore[no-untyped-def]
    global _redis
    s = get_settings()
    if _redis is None and s.redis_url:
        try:
            import redis

            _redis = redis.Redis.from_url(s.redis_url, socket_timeout=0.5)
            _redis.ping()
        except Exception:  # noqa: BLE001
            _redis = False
    return _redis or None


def check_rate_limit(key: str, limit: int | None = None, window_seconds: int = 60) -> None:
    limit = limit or get_settings().rate_limit_per_minute
    now = time.time()
    r = _redis_client()
    if r is not None:
        try:
            bucket = f"rl:{key}:{int(now // window_seconds)}"
            n = r.incr(bucket)
            if n == 1:
                r.expire(bucket, window_seconds)
            if n > limit:
                raise RateLimited("Rate limit exceeded", details={"limit": limit, "window_seconds": window_seconds})
            return
        except RateLimited:
            raise
        except Exception:  # noqa: BLE001 - fall back to in-memory
            pass
    with _lock:
        q = _windows.setdefault(key, deque())
        while q and q[0] < now - window_seconds:
            q.popleft()
        if len(q) >= limit:
            raise RateLimited("Rate limit exceeded", details={"limit": limit, "window_seconds": window_seconds})
        q.append(now)


def reset_rate_limits() -> None:
    with _lock:
        _windows.clear()
