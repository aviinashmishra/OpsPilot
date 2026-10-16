"""Integration adapter contract.

An adapter wraps one provider family (crm, email, slack, tasks, commerce,
accounting, whatsapp, workspace, monitoring, procurement). Each family exposes a
fixed set of typed methods. Two implementations exist per family:

* a **mock** adapter operating on the tenant's sandbox records in the database
  (always available, used for local development, demos and tests), and
* a **live** adapter calling the provider's documented HTTP API with credentials
  stored encrypted on the Integration row (only used when the integration is
  configured, connected and its last connection test succeeded).

The platform never reports a live integration as connected unless a real
`test_connection()` succeeded.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field

from app.core.errors import CircuitOpen, IntegrationError, RateLimited, TransientIntegrationError
from app.core.logging import get_logger

log = get_logger("integrations")


class ConnectionTestResult(BaseModel):
    ok: bool
    mode: str  # mock|live
    provider: str
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    checked_at: float = Field(default_factory=time.time)


class VerificationResult(BaseModel):
    """Outcome of reconciling an external action whose result was unknown (timeout/crash)."""

    verified: bool
    exists: bool | None = None
    external_ref: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class BaseAdapter:
    provider: ClassVar[str] = "base"
    mode: ClassVar[str] = "mock"
    capabilities: ClassVar[list[str]] = []
    display_name: ClassVar[str] = "Base"

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, mode=self.mode, provider=self.provider, message="mock adapter always available")

    def verify_action(self, method: str, request: dict[str, Any], external_ref: str | None) -> VerificationResult | None:
        """Reconcile a possibly-executed side effect. Return None when the provider cannot verify."""
        return None


# ---------------------------------------------------------------------------
# Resilience helpers for live adapters
# ---------------------------------------------------------------------------


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_seconds: float = 60.0
    failures: int = 0
    opened_at: float | None = None
    state: str = "closed"

    def before_call(self) -> None:
        if self.state == "open":
            assert self.opened_at is not None
            if time.time() - self.opened_at >= self.recovery_seconds:
                self.state = "half_open"
            else:
                raise CircuitOpen("Circuit breaker open for provider", details={"retry_after_s": self.recovery_seconds})

    def record_success(self) -> None:
        self.failures = 0
        self.state = "closed"
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold or self.state == "half_open":
            self.state = "open"
            self.opened_at = time.time()


_breakers: dict[str, CircuitBreaker] = {}


def breaker_for(key: str) -> CircuitBreaker:
    return _breakers.setdefault(key, CircuitBreaker())


def reset_breakers() -> None:
    _breakers.clear()


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter: float = 0.3
    retry_on: tuple[type[Exception], ...] = (TransientIntegrationError, RateLimited)

    def delay(self, attempt: int) -> float:
        d = min(self.max_delay, self.base_delay * (2**attempt))
        return d + random.uniform(0, self.jitter * d)


def with_retry(fn: Callable[[], Any], policy: RetryPolicy | None = None, *, safe_to_retry: bool = True, sleep: Callable[[float], None] = time.sleep) -> Any:
    """Retry transient failures with exponential backoff + jitter.

    `safe_to_retry=False` disables retries entirely (non-idempotent operations
    must go through outcome verification instead of blind retries).
    """
    policy = policy or RetryPolicy()
    attempts = policy.max_attempts if safe_to_retry else 1
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except policy.retry_on as exc:  # type: ignore[misc]
            last = exc
            if attempt + 1 >= attempts:
                break
            sleep(policy.delay(attempt))
    assert last is not None
    raise last


@dataclass
class HttpClientConfig:
    base_url: str
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 15.0
    breaker_key: str = "default"


class LiveHttpAdapter(BaseAdapter):
    """Shared plumbing for live adapters: timeouts, retries, rate-limit mapping, breaker."""

    mode = "live"

    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config
        self._client = httpx.Client(base_url=config.base_url, headers=config.headers, timeout=config.timeout)
        self._breaker = breaker_for(config.breaker_key)

    def _request(self, method: str, path: str, *, safe_to_retry: bool = True, **kwargs: Any) -> httpx.Response:
        def _do() -> httpx.Response:
            self._breaker.before_call()
            try:
                resp = self._client.request(method, path, **kwargs)
            except httpx.TimeoutException as exc:
                self._breaker.record_failure()
                raise TransientIntegrationError(f"{self.provider}: timeout", details={"path": path}) from exc
            except httpx.TransportError as exc:
                self._breaker.record_failure()
                raise TransientIntegrationError(f"{self.provider}: transport error", details={"path": path}) from exc
            if resp.status_code == 429:
                self._breaker.record_failure()
                retry_after = resp.headers.get("Retry-After")
                raise RateLimited(f"{self.provider}: rate limited", details={"retry_after": retry_after})
            if resp.status_code >= 500:
                self._breaker.record_failure()
                raise TransientIntegrationError(f"{self.provider}: server error {resp.status_code}", details={"path": path})
            if resp.status_code >= 400:
                self._breaker.record_success()
                raise IntegrationError(
                    f"{self.provider}: request failed ({resp.status_code})",
                    details={"path": path, "body": resp.text[:500]},
                )
            self._breaker.record_success()
            return resp

        return with_retry(_do, safe_to_retry=safe_to_retry)

    def close(self) -> None:
        self._client.close()
