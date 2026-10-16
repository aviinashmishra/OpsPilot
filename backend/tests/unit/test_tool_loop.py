"""The agentic tool loop, driven by a fake Claude client (no network).

Verifies the Messages API protocol contract: parallel tool_use blocks are all
answered in ONE user message, failures come back as is_error results, the
assistant content is replayed verbatim, and the loop is bounded.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.core.errors import LLMError
from app.llm.gateway import LLMGateway
from app.llm.tool_loop import LoopTool, ToolOutcome, run_tool_loop


class Block(SimpleNamespace):
    def model_dump(self, **_: Any) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def msg(blocks: list[Block], stop: str) -> SimpleNamespace:
    return SimpleNamespace(content=blocks, stop_reason=stop, model="claude-opus-5-5", usage=SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=80, cache_creation_input_tokens=0))


class FakeClaude:
    name = "anthropic"

    def __init__(self, script: list[SimpleNamespace]) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    def create_with_tools(self, **kw: Any) -> SimpleNamespace:
        self.requests.append({**kw, "messages": [dict(m) for m in kw["messages"]]})
        return self.script.pop(0)


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def started(self, iteration: int, tool: LoopTool, call_input: dict[str, Any]) -> str:
        self.events.append(("start", tool.name))
        return tool.name

    def finished(self, handle: str, outcome: ToolOutcome, duration_ms: int) -> None:
        self.events.append(("end", handle))


class NoPlanner:
    def plan(self, *a: Any) -> list[Any]:
        return []

    def answer(self, *a: Any) -> str:
        return ""


def _tools() -> list[LoopTool]:
    def stock(data: dict[str, Any]) -> ToolOutcome:
        return ToolOutcome(content={"sku": data["sku"], "on_hand": 3}, summary="3 on hand")

    def boom(_: dict[str, Any]) -> ToolOutcome:
        raise RuntimeError("upstream exploded")

    schema = {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]}
    return [LoopTool("get_stock", "stock", schema, "tool", "Stock", stock), LoopTool("broken", "fails", {"type": "object", "properties": {}}, "tool", "Broken", boom)]


def test_parallel_tool_calls_answered_in_one_message_and_errors_flagged():
    fake = FakeClaude([
        msg([Block(type="text", text="Checking both."), Block(type="tool_use", id="tu_1", name="get_stock", input={"sku": "A"}), Block(type="tool_use", id="tu_2", name="broken", input={})], "tool_use"),
        msg([Block(type="text", text="A has 3 on hand; the other lookup failed.")], "end_turn"),
    ])
    rec = Recorder()
    result = run_tool_loop(gateway=LLMGateway(provider=fake), system="sys", history=[], user_text="check", tools=_tools(), observer=rec, planner=NoPlanner())
    assert result.mode == "claude" and result.text.startswith("A has 3") and result.tool_calls == 2
    second = fake.requests[1]["messages"]
    assert second[1]["role"] == "assistant" and second[1]["content"][1]["type"] == "tool_use"
    results = second[2]
    assert results["role"] == "user" and len(results["content"]) == 2  # one message, both results
    by_id = {r["tool_use_id"]: r for r in results["content"]}
    assert '"on_hand": 3' in by_id["tu_1"]["content"] and "is_error" not in by_id["tu_1"]
    assert by_id["tu_2"]["is_error"] is True and "upstream exploded" in by_id["tu_2"]["content"]
    assert rec.events == [("start", "get_stock"), ("end", "get_stock"), ("start", "broken"), ("end", "broken")]
    assert result.new_history[0] == {"role": "user", "content": "check"} and len(result.new_history) == 4
    assert result.usage["cache_read_input_tokens"] == 160 and result.usage["cost_usd"] > 0
    assert fake.requests[0]["tools"][0]["name"] == "get_stock"


def test_unknown_tool_and_iteration_and_call_budgets():
    loop_forever = [msg([Block(type="tool_use", id=f"t{i}", name="nope", input={})], "tool_use") for i in range(5)]
    fake = FakeClaude(loop_forever)
    result = run_tool_loop(gateway=LLMGateway(provider=fake), system="s", history=[], user_text="x", tools=_tools(), observer=Recorder(), planner=NoPlanner(), max_iterations=3)
    assert len(fake.requests) == 3 and any("step" in w for w in result.warnings)
    assert "Unknown tool" in fake.requests[1]["messages"][-1]["content"][0]["content"]

    fake2 = FakeClaude([msg([Block(type="tool_use", id="a", name="get_stock", input={"sku": "A"}), Block(type="tool_use", id="b", name="get_stock", input={"sku": "B"})], "tool_use"), msg([Block(type="text", text="ok")], "end_turn")])
    run_tool_loop(gateway=LLMGateway(provider=fake2), system="s", history=[], user_text="x", tools=_tools(), observer=Recorder(), planner=NoPlanner(), max_tool_calls=1)
    second = fake2.requests[1]["messages"][-1]["content"]
    assert "is_error" not in second[0] and second[1]["is_error"] is True and "budget" in second[1]["content"]


def test_history_is_replayed_append_only():
    fake = FakeClaude([msg([Block(type="text", text="second answer")], "end_turn")])
    prior = [{"role": "user", "content": "first"}, {"role": "assistant", "content": [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": "first answer"}]}]
    run_tool_loop(gateway=LLMGateway(provider=fake), system="s", history=prior, user_text="again", tools=_tools(), observer=Recorder(), planner=NoPlanner())
    sent = fake.requests[0]["messages"]
    assert sent[:2] == prior and sent[2] == {"role": "user", "content": "again"}


def test_max_tokens_stop_is_reported():
    fake = FakeClaude([msg([Block(type="text", text="partial")], "max_tokens")])
    result = run_tool_loop(gateway=LLMGateway(provider=fake), system="s", history=[], user_text="x", tools=_tools(), observer=Recorder(), planner=NoPlanner())
    assert result.stop_reason == "max_tokens" and any("max_tokens" in w for w in result.warnings)


def test_anthropic_provider_request_shape(monkeypatch):
    """AnthropicProvider sends cached system + tools, effort, and server-side fallbacks; refusals raise."""
    import pytest

    from app.core.errors import LLMError
    from app.llm import gateway as g

    captured: dict[str, Any] = {}

    class FakeMessages:
        def create(self, **kw: Any) -> Any:
            captured.update(kw)
            return msg([Block(type="text", text="hi")], kw.pop("_stop", "end_turn"))

    provider = g.AnthropicProvider.__new__(g.AnthropicProvider)
    import anthropic

    provider._anthropic = anthropic
    provider._client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
    provider._fallback_kwargs = {"betas": [g.FALLBACK_BETA], "fallbacks": "default"}
    provider.create_with_tools(model="claude-opus-5-5", system="S", messages=[{"role": "user", "content": "x"}], tools=[{"name": "a", "description": "d", "input_schema": {"type": "object"}}, {"name": "b", "description": "d", "input_schema": {"type": "object"}}], max_tokens=16000, timeout=60, effort="high")
    assert captured["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert captured["tools"][-1]["cache_control"] == {"type": "ephemeral"} and "cache_control" not in captured["tools"][0]
    assert captured["output_config"] == {"effort": "high"} and captured["fallbacks"] == "default" and captured["betas"] == [g.FALLBACK_BETA]
    assert "tool_choice" not in captured and "thinking" not in captured and "temperature" not in captured

    class Refusing:
        def create(self, **kw: Any) -> Any:
            m = msg([], "refusal")
            m.stop_details = SimpleNamespace(category="cyber")
            return m

    provider._client = SimpleNamespace(beta=SimpleNamespace(messages=Refusing()))
    with pytest.raises(LLMError) as exc:
        provider.complete(model="claude-opus-5-5", system="s", user="u", max_tokens=100, timeout=10, json_mode=True)
    assert exc.value.retryable is False and exc.value.details["category"] == "cyber"


def test_transient_provider_errors_are_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import tool_loop

    monkeypatch.setattr(tool_loop.time, "sleep", lambda _s: None)
    calls: list[int] = []

    def flaky(**_: Any) -> str:
        calls.append(1)
        if len(calls) < 3:
            raise LLMError("Gemini API error 503: overloaded")
        return "ok"

    assert tool_loop._create_with_retry(flaky, model="m") == "ok" and len(calls) == 3

    fatal = LLMError("bad request")
    fatal.retryable = False
    calls.clear()

    def broken(**_: Any) -> str:
        calls.append(1)
        raise fatal

    with pytest.raises(LLMError):
        tool_loop._create_with_retry(broken, model="m")
    assert len(calls) == 1