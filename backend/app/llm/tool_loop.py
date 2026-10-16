"""Provider-agnostic agentic tool-use loop.

Claude mode (LLM_PROVIDER=anthropic)
    The manual Messages API loop: send tools + history, execute every `tool_use`
    block the model returns (it may return several in parallel), send all
    `tool_result` blocks back in ONE user message (failures flagged `is_error`),
    repeat until `stop_reason == "end_turn"`. Bounded by `max_iterations` and
    `max_tool_calls`; `max_tokens`, `pause_turn` and `refusal` are handled
    explicitly. History is append-only (assistant content is stored verbatim,
    thinking blocks included) so it can be replayed on the next turn.

    A manual loop (rather than the SDK's beta tool runner) is used on purpose:
    every tool call must pass through OpsPilot's tenant-scoped permission and
    policy checks, be persisted as a live step for the dashboard, and the same
    loop must also run offline.

Gemini mode (LLM_PROVIDER=gemini)
    The same loop and the same stored history format: GeminiProvider converts the
    Anthropic-shaped history to Gemini contents per call and returns its reply as
    text / tool_use blocks (thought signatures carried along), so nothing here changes.

Offline mode (LLM_PROVIDER=mock)
    A deterministic `Planner` chooses tool calls from the request; the exact
    same execution, persistence and policy path runs. The result is labelled
    ``mode="offline_planner"`` so nobody mistakes it for model output.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import get_settings
from app.core.errors import LLMError
from app.core.logging import get_logger
from app.llm.gateway import LLMGateway, estimate_cost

log = get_logger("tool_loop")
MAX_RESULT_CHARS = 12_000


@dataclass
class ToolOutcome:
    content: Any
    summary: str = ""
    is_error: bool = False
    status: str = "ok"  # ok | error | needs_approval
    approval_ids: list[str] = field(default_factory=list)
    agent_run_id: str | None = None
    workflow_run_id: str | None = None


@dataclass
class LoopTool:
    name: str  # API-safe: ^[a-zA-Z0-9_-]{1,64}$
    description: str
    input_schema: dict[str, Any]
    kind: str  # agent | tool | custom | platform
    label: str
    run: Callable[[dict[str, Any]], ToolOutcome]

    def definition(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description[:1024], "input_schema": self.input_schema or {"type": "object", "properties": {}}}


@dataclass
class PlannedCall:
    name: str
    input: dict[str, Any]


class Planner(Protocol):
    def plan(self, user_text: str, done: list[tuple[PlannedCall, ToolOutcome]], iteration: int, tools: dict[str, LoopTool]) -> list[PlannedCall]: ...

    def answer(self, user_text: str, done: list[tuple[PlannedCall, ToolOutcome]]) -> str: ...


class StepObserver(Protocol):
    def started(self, iteration: int, tool: LoopTool, call_input: dict[str, Any]) -> Any: ...

    def finished(self, handle: Any, outcome: ToolOutcome, duration_ms: int) -> None: ...


@dataclass
class LoopResult:
    text: str
    new_history: list[dict[str, Any]]
    mode: str
    model: str | None
    stop_reason: str
    iterations: int
    tool_calls: int
    usage: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def _result_text(outcome: ToolOutcome) -> str:
    try:
        body = json.dumps(outcome.content, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        body = str(outcome.content)
    if len(body) > MAX_RESULT_CHARS:
        body = body[:MAX_RESULT_CHARS] + '..."[truncated]"'
    return body


def _execute(tool: LoopTool | None, name: str, call_input: dict[str, Any], iteration: int, observer: StepObserver) -> ToolOutcome:
    if tool is None:
        return ToolOutcome(content={"error": f"Unknown tool '{name}'"}, summary=f"Unknown tool {name}", is_error=True, status="error")
    handle = observer.started(iteration, tool, call_input)
    started = time.perf_counter()
    try:
        outcome = tool.run(call_input if isinstance(call_input, dict) else {})
    except Exception as exc:  # noqa: BLE001 - surfaced to the model as an error result, never raised
        log.warning("tool_loop.tool_failed", tool=name, error=str(exc)[:300])
        message = getattr(exc, "message", None) or str(exc)
        details = getattr(exc, "details", None)
        outcome = ToolOutcome(content={"error": message[:2000], "details": details or {}}, summary=f"Error: {message[:200]}", is_error=True, status="error")
    observer.finished(handle, outcome, int((time.perf_counter() - started) * 1000))
    return outcome


def _create_with_retry(create: Callable[..., Any], *, attempts: int = 3, **kwargs: Any) -> Any:
    """One model turn, retrying transient provider errors (429 / 5xx / connection) with backoff.

    Without this a single "model overloaded" 503 fails the whole Copilot answer, unlike the
    structured gateway calls which already retry."""
    for attempt in range(attempts):
        try:
            return create(**kwargs)
        except LLMError as exc:
            if not exc.retryable or attempt == attempts - 1:
                raise
            log.warning("tool_loop.provider_retry", attempt=attempt, error=str(exc)[:200])
            time.sleep(min(2**attempt * 1.5, 8))
    raise AssertionError("unreachable")


def run_tool_loop(
    *,
    gateway: LLMGateway,
    system: str,
    history: list[dict[str, Any]],
    user_text: str,
    tools: list[LoopTool],
    observer: StepObserver,
    planner: Planner,
    max_iterations: int | None = None,
    max_tool_calls: int | None = None,
    effort: str | None = None,
    model: str | None = None,
) -> LoopResult:
    s = get_settings()
    max_iterations = max_iterations or s.copilot_max_iterations
    max_tool_calls = max_tool_calls or s.copilot_max_tool_calls
    by_name = {t.name: t for t in tools}
    create = getattr(gateway.provider, "create_with_tools", None)
    if gateway.is_mock or create is None:
        return _run_offline(user_text, by_name, observer, planner, max_iterations, max_tool_calls)

    resolved_model = model or gateway.resolve_model("default")
    messages: list[dict[str, Any]] = list(history) + [{"role": "user", "content": user_text}]
    turn_start = len(messages) - 1
    definitions = [t.definition() for t in tools]
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "cost_usd": 0.0, "calls": 0}
    calls = 0
    warnings: list[str] = []
    stop_reason = "end_turn"
    text = ""
    for iteration in range(1, max_iterations + 1):
        msg = _create_with_retry(create, model=resolved_model, system=system, messages=messages, tools=definitions, max_tokens=16000, timeout=s.llm_timeout_seconds * 3, effort=effort or s.copilot_effort)
        u = msg.usage
        usage["calls"] += 1
        usage["input_tokens"] += u.input_tokens or 0
        usage["output_tokens"] += u.output_tokens or 0
        usage["cache_read_input_tokens"] += getattr(u, "cache_read_input_tokens", 0) or 0
        usage["cache_creation_input_tokens"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        usage["cost_usd"] = round(usage["cost_usd"] + estimate_cost(msg.model, (u.input_tokens or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0), u.output_tokens or 0), 6)
        content = [block.model_dump(mode="json", exclude_none=True) for block in msg.content]
        messages.append({"role": "assistant", "content": content})
        stop_reason = msg.stop_reason or "end_turn"
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        if stop_reason == "pause_turn":
            continue
        if stop_reason == "max_tokens":
            warnings.append("Response hit max_tokens and may be incomplete")
            break
        if stop_reason != "tool_use":
            break
        results: list[dict[str, Any]] = []
        for block in msg.content:
            if block.type != "tool_use":
                continue
            if calls >= max_tool_calls:
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": "Tool-call budget for this request is exhausted; answer with what you have.", "is_error": True})
                continue
            calls += 1
            outcome = _execute(by_name.get(block.name), block.name, dict(block.input or {}), iteration, observer)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": _result_text(outcome), **({"is_error": True} if outcome.is_error else {})})
        messages.append({"role": "user", "content": results})
        if iteration == max_iterations:
            warnings.append(f"Stopped after {max_iterations} reasoning steps")
            text = text or "I reached the step limit for one request. The tool results gathered so far are shown above."
    if not text:
        text = "Done." if stop_reason == "end_turn" else "I could not complete this request."
    return LoopResult(text=text, new_history=messages[turn_start:], mode=gateway.copilot_mode, model=resolved_model, stop_reason=stop_reason, iterations=usage["calls"], tool_calls=calls, usage=usage, warnings=warnings)


def _run_offline(user_text: str, by_name: dict[str, LoopTool], observer: StepObserver, planner: Planner, max_iterations: int, max_tool_calls: int) -> LoopResult:
    done: list[tuple[PlannedCall, ToolOutcome]] = []
    iterations = 0
    for iteration in range(1, max_iterations + 1):
        planned = planner.plan(user_text, done, iteration, by_name)
        if not planned:
            break
        iterations = iteration
        for call in planned:
            if len(done) >= max_tool_calls:
                break
            outcome = _execute(by_name.get(call.name), call.name, call.input, iteration, observer)
            done.append((call, outcome))
    text = planner.answer(user_text, done)
    history = [{"role": "user", "content": user_text}, {"role": "assistant", "content": text}]
    return LoopResult(text=text, new_history=history, mode="offline_planner", model=None, stop_reason="end_turn", iterations=iterations, tool_calls=len(done), usage={"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})


def new_call_id() -> str:
    return f"call_{uuid.uuid4().hex[:12]}"


LLMError  # noqa: B018 - re-export for callers
