"""Multi-provider, quota-aware failover for the LLM gateway.

`FailoverProvider` is a drop-in `LLMProvider`: the gateway, the agents and the Copilot tool loop
call it exactly like a single provider, and it routes each call through an ordered list of
(provider, model) routes:

  primary model  ->  other Gemini models (separate free-tier quotas)  ->  Claude / OpenAI (if keyed)

* A route that answers 429 (rate limit or quota) is "cooled" for exactly as long as the provider
  says ("retry in 13h8m"), or a sensible default; 5xx / overloaded / connection errors cool it for
  30 s. The next route is tried immediately: no sleeping on a provider that is known to be down.
* Non-availability errors (bad request, safety refusal, schema problems) are raised unchanged.
* When every route is cooling, a non-retryable `LLMError` is raised at once, so agents switch to
  their deterministic logic and the Copilot to its offline planner without waiting on retries.

Cooldowns are process-wide (shared by all gateways in the process) and exposed by `status()`
for the dashboard.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.errors import LLMError, LLMOutputInvalid
from app.core.logging import get_logger

log = get_logger("llm.failover")

QUOTA_DEFAULT_S = 3600.0  # daily quota without a retry hint: probe again hourly
RATE_DEFAULT_S = 60.0
UNAVAILABLE_S = 30.0
MAX_COOLDOWN_S = 86_400.0
EFFORT_PROVIDERS = {"anthropic", "gemini"}
# Fields the Messages API accepts in content blocks; anything else (e.g. Gemini thought signatures)
# is dropped before a Gemini-written history is sent to Claude.
_ANTHROPIC_BLOCK_KEYS = {"type", "text", "id", "name", "input", "tool_use_id", "content", "is_error", "thinking", "signature", "data", "citations"}


def model_family(model: str) -> str | None:
    if model.startswith("claude"):
        return "anthropic"
    if model.startswith("gemini"):
        return "gemini"
    if model.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    return None


@dataclass
class Route:
    provider: Any
    default_model: str
    fast_model: str

    @property
    def key(self) -> str:
        return f"{self.provider.name}:{self.default_model}"

    @property
    def supports_tools(self) -> bool:
        return hasattr(self.provider, "create_with_tools")


class _Health:
    """Process-wide cooldown registry, keyed by route."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._until: dict[str, float] = {}
        self._reason: dict[str, str] = {}

    def cooling_until(self, key: str) -> float | None:
        with self._lock:
            until = self._until.get(key)
            if until and until > time.time():
                return until
            self._until.pop(key, None)
            return None

    def cool(self, key: str, seconds: float, reason: str) -> None:
        with self._lock:
            self._until[key] = time.time() + min(max(seconds, 1.0), MAX_COOLDOWN_S)
            self._reason[key] = reason

    def clear(self, key: str) -> None:
        with self._lock:
            self._until.pop(key, None)

    def reason(self, key: str) -> str | None:
        with self._lock:
            return self._reason.get(key)

    def reset(self) -> None:
        with self._lock:
            self._until.clear()
            self._reason.clear()


HEALTH = _Health()


def cooldown_for(exc: LLMError) -> tuple[float, str] | None:
    """How long to rest a route after this error, or None when it is not an availability problem."""
    details = exc.details or {}
    text = str(exc).lower()
    hinted = details.get("retry_after_s")
    if details.get("status") == 429 or "rate limit" in text or "resource_exhausted" in text or "quota" in text:
        if details.get("daily_quota") or "quota" in text:
            return float(hinted or QUOTA_DEFAULT_S), "quota exhausted"
        return float(hinted or RATE_DEFAULT_S), "rate limited"
    if exc.retryable:
        return float(hinted or UNAVAILABLE_S), "unavailable"
    return None


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat() if ts else None


class FailoverProvider:
    """An `LLMProvider` that spreads calls over several routes; see the module docstring."""

    name = "failover"

    def __init__(self, routes: list[Route]) -> None:
        if not routes:
            raise ValueError("FailoverProvider needs at least one route")
        self.routes = routes
        self._local = threading.local()

    # -- bookkeeping ------------------------------------------------------
    @property
    def last_used(self) -> str | None:
        """Provider name that served the most recent call on this thread (for usage records)."""
        return getattr(self._local, "provider", None)

    @property
    def primary(self) -> Route:
        return self.routes[0]

    def available_routes(self, *, tools: bool = False) -> list[Route]:
        return [r for r in self.routes if (r.supports_tools or not tools) and HEALTH.cooling_until(r.key) is None]

    def active_route(self, *, tools: bool = False) -> Route | None:
        avail = self.available_routes(tools=tools)
        return avail[0] if avail else None

    def status(self) -> dict[str, Any]:
        rows = []
        for r in self.routes:
            until = HEALTH.cooling_until(r.key)
            rows.append({"provider": r.provider.name, "model": r.default_model, "fast_model": r.fast_model, "tools": r.supports_tools, "state": "cooling" if until else "ready", "until": _iso(until), "reason": HEALTH.reason(r.key) if until else None})
        active = self.active_route()
        next_at = min((HEALTH.cooling_until(r.key) or 0 for r in self.routes), default=0) if active is None else None
        return {"available": active is not None, "active": {"provider": active.provider.name, "model": active.default_model} if active else None, "next_available_at": _iso(next_at) if next_at else None, "routes": rows}

    # -- routing ------------------------------------------------------------
    def _plan(self, model: str, *, tools: bool) -> list[tuple[Route, str]]:
        """Routes to try, each with the model to use on it. The caller's model picks the tier
        (default/fast) on the primary; a model from another family (an agent model override)
        moves a route of that family to the front."""
        primary = self.primary
        tier = "fast" if model == primary.fast_model and model != primary.default_model else "default"
        family = model_family(model)
        override = model not in (primary.default_model, primary.fast_model)
        plan: list[tuple[Route, str]] = []
        for r in self.routes:
            if tools and not r.supports_tools:
                continue
            m = r.fast_model if tier == "fast" else r.default_model
            if override and family == r.provider.name and not any(p[0].provider is r.provider for p in plan):
                plan.insert(0, (r, model))
                continue
            plan.append((r, m))
        return plan

    def _run(self, model: str, call: Any, *, tools: bool = False) -> Any:
        from app.llm.gateway import SchemaUnsupported

        plan = self._plan(model, tools=tools)
        last: LLMError | None = None
        for route, route_model in plan:
            if HEALTH.cooling_until(route.key):
                continue
            try:
                result = call(route.provider, route_model)
            except SchemaUnsupported:
                raise
            except LLMError as exc:
                cooldown = cooldown_for(exc)
                if cooldown is None:
                    raise
                HEALTH.cool(route.key, *cooldown)
                log.warning("llm.failover", route=route.key, reason=cooldown[1], cooldown_s=round(cooldown[0]), error=str(exc)[:200])
                last = exc
                continue
            self._local.provider = route.provider.name
            return result
        raise self._unavailable(plan, last)

    def _unavailable(self, plan: list[tuple[Route, str]], last: LLMError | None) -> LLMError:
        until = [u for u in (HEALTH.cooling_until(r.key) for r, _ in plan) if u]
        err = LLMError(
            "No AI provider is available right now" + (f" (last error: {str(last)[:160]})" if last else ""),
            details={"provider": "failover", "next_available_at": _iso(min(until)) if until else None, "routes": [r.key for r, _ in plan]},
        )
        err.retryable = False  # retrying immediately cannot help: every route is cooling
        return err

    # -- LLMProvider API ------------------------------------------------------
    def complete(self, *, model: str, system: str, user: str, max_tokens: int, timeout: int, json_mode: bool, effort: str | None = None) -> Any:
        def call(p: Any, m: str) -> Any:
            extra = {"effort": effort} if p.name in EFFORT_PROVIDERS else {}
            return p.complete(model=m, system=system, user=user, max_tokens=max_tokens, timeout=timeout, json_mode=json_mode, **extra)

        return self._run(model, call)

    def parse(self, *, model: str, system: str, user: str, schema: Any, max_tokens: int, timeout: int, effort: str | None = None) -> Any:
        def call(p: Any, m: str) -> Any:
            if hasattr(p, "parse"):
                extra = {"effort": effort} if p.name in EFFORT_PROVIDERS else {}
                return p.parse(model=m, system=system, user=user, schema=schema, max_tokens=max_tokens, timeout=timeout, **extra)
            return _parse_via_json(p, m, system=system, user=user, schema=schema, max_tokens=max_tokens, timeout=timeout)

        return self._run(model, call)

    def create_with_tools(self, *, model: str, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int, timeout: int, effort: str | None = None) -> Any:
        def call(p: Any, m: str) -> Any:
            history = _for_anthropic(messages) if p.name == "anthropic" else messages
            return p.create_with_tools(model=m, system=system, messages=history, tools=tools, max_tokens=max_tokens, timeout=timeout, effort=effort)

        return self._run(model, call, tools=True)


def _parse_via_json(p: Any, model: str, *, system: str, user: str, schema: Any, max_tokens: int, timeout: int) -> Any:
    """Structured output for providers without native parsing (OpenAI): JSON mode + validation."""
    import json

    from pydantic import ValidationError

    from app.llm.gateway import _extract_json

    hint = json.dumps(schema.model_json_schema(), separators=(",", ":"))
    resp = p.complete(model=model, system=f"{system}\n\nAnswer with one JSON object that validates against this JSON schema:\n{hint}", user=user, max_tokens=max_tokens, timeout=timeout, json_mode=True)
    try:
        return schema.model_validate(_extract_json(resp.text)), resp
    except (ValueError, ValidationError) as exc:
        raise LLMOutputInvalid(f"{p.name} returned output that does not match the schema") from exc


def _for_anthropic(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip provider-specific fields (Gemini thought signatures) from a stored history."""
    out = []
    for m in messages:
        content = m["content"]
        if isinstance(content, list):
            content = [{k: v for k, v in b.items() if k in _ANTHROPIC_BLOCK_KEYS} for b in content if isinstance(b, dict)]
            content = [b for b in content if b.get("type") != "text" or b.get("text")]  # Gemini signature-only text parts
        out.append({**m, "content": content})
    return out
