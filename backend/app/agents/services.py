"""Services handed to an agent at run time.

`ToolInvoker` is the *only* path from an agent to the outside world. It enforces:
* the agent's declared allowed_tools,
* the actor's permission scopes,
* read-only access (side-effecting tools must be proposed, never invoked),
* per-run call limits, and
* full recording of every call as a ToolExecution row.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError, OpsPilotError, ToolNotAllowed, ValidationFailed
from app.core.logging import get_logger
from app.db.models import ToolExecution
from app.integrations.resolver import AdapterResolver
from app.llm.gateway import BudgetTracker, LLMGateway
from app.tools.registry import tool_registry

if TYPE_CHECKING:
    from app.agents.base import AgentContext

log = get_logger("agent.services")
MAX_TOOL_CALLS_PER_RUN = 40


class ToolInvoker:
    def __init__(self, db: Session, ctx: AgentContext, allowed_tools: list[str], resolver: AdapterResolver | None = None) -> None:
        self.db = db
        self.ctx = ctx
        self.allowed = set(allowed_tools)
        self.resolver = resolver or AdapterResolver(db, ctx.tenant_id)
        self.calls: list[dict[str, Any]] = []
        self.modes_used: set[str] = set()

    def call(self, tool_key: str, **payload: Any) -> dict[str, Any]:
        if len(self.calls) >= MAX_TOOL_CALLS_PER_RUN:
            raise ToolNotAllowed("Tool call limit for this agent run exceeded", details={"limit": MAX_TOOL_CALLS_PER_RUN})
        if tool_key not in self.allowed:
            raise ToolNotAllowed(f"Agent is not allowed to use tool '{tool_key}'", details={"tool": tool_key})
        spec = tool_registry.get(tool_key)
        if spec.side_effect:
            raise ToolNotAllowed(
                f"Tool '{tool_key}' has side effects and must be proposed as an action, not invoked directly",
                details={"tool": tool_key},
            )
        if not self.ctx.has_permission(spec.required_permission):
            raise AuthorizationError(f"Missing permission '{spec.required_permission}' for tool '{tool_key}'")
        try:
            clean = tool_registry.validate_payload(tool_key, payload)
        except ValidationError as exc:
            raise ValidationFailed(f"Invalid payload for tool '{tool_key}'", details={"errors": exc.errors()[:5]}) from exc

        resolved = self.resolver.resolve(spec.provider)
        self.modes_used.add(resolved.mode)
        rec = ToolExecution(
            tenant_id=uuid.UUID(self.ctx.tenant_id),
            run_id=uuid.UUID(self.ctx.workflow_run_id) if self.ctx.workflow_run_id else None,
            agent_run_id=uuid.UUID(self.ctx.agent_run_id) if self.ctx.agent_run_id else None,
            integration_id=resolved.integration_id,
            tool_key=tool_key,
            provider=spec.provider,
            mode=resolved.mode,
            side_effect=False,
            request=clean,
            status="in_progress",
            attempt=1,
            actor_id=self.ctx.actor_id,
            correlation_id=self.ctx.correlation_id,
            started_at=datetime.now(UTC),
        )
        self.db.add(rec)
        self.db.flush()
        started = time.perf_counter()
        try:
            method = getattr(resolved.adapter, spec.method)
            result = method(**clean)
            if not isinstance(result, dict):
                result = {"result": result}
            rec.status = "succeeded"
            rec.response = _truncate(result)
            return result
        except OpsPilotError as exc:
            rec.status = "failed"
            rec.error = exc.to_dict()
            raise
        except Exception as exc:  # noqa: BLE001
            rec.status = "failed"
            rec.error = {"code": "tool_exception", "message": str(exc)[:500]}
            raise OpsPilotError(f"Tool '{tool_key}' failed: {exc}") from exc
        finally:
            rec.finished_at = datetime.now(UTC)
            self.db.flush()
            self.calls.append({"tool": tool_key, "mode": resolved.mode, "status": rec.status, "ms": int((time.perf_counter() - started) * 1000)})


def _truncate(data: Any, max_items: int = 200) -> Any:
    """Bound stored tool responses so a huge listing cannot bloat the row."""
    if isinstance(data, dict):
        return {k: _truncate(v, max_items) for k, v in list(data.items())[:max_items]}
    if isinstance(data, list):
        return [_truncate(v, max_items) for v in data[:max_items]]
    if isinstance(data, str) and len(data) > 4000:
        return data[:4000] + "...[truncated]"
    return data


class AgentServices:
    def __init__(self, db: Session, ctx: AgentContext, allowed_tools: list[str], llm: LLMGateway, token_budget: int, model_override: str | None = None) -> None:
        self.db = db
        self.ctx = ctx
        self.tools = ToolInvoker(db, ctx, allowed_tools)
        self.llm = llm
        self.budget = BudgetTracker(token_budget=token_budget)
        self.model_override = model_override
        self.log = log.bind(tenant_id=ctx.tenant_id, correlation_id=ctx.correlation_id)

    def structured(self, *, task: str, schema: Any, system: str, user: str, heuristic: Any, tier: str = "default") -> Any:
        """Convenience wrapper that applies the budget and model override."""
        result, _usage = self.llm.structured(
            task=task,
            schema=schema,
            system=system,
            user=user,
            heuristic=heuristic,
            budget=self.budget,
            model=self.model_override,
            tier=tier,
        )
        return result

    @property
    def now(self) -> datetime:
        return self.ctx.now
