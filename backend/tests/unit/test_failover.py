"""Multi-provider, quota-aware failover (no network)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import LLMError
from app.llm import gateway as g
from app.llm.failover import HEALTH, FailoverProvider, Route, cooldown_for
from app.llm.gateway import LLMGateway, ProviderResponse, retry_after_seconds
from app.llm.tool_loop import AI_UNAVAILABLE_WARNING, LoopTool, ToolOutcome, run_tool_loop


class Out(BaseModel):
    answer: str


def quota_error(provider: str = "gemini", hint: str = "Please retry in 2h3m4s.") -> LLMError:
    err = LLMError(f"{provider} API error 429: You exceeded your current quota. {hint}", details={"provider": provider, "status": 429, "retry_after_s": retry_after_seconds(hint), "daily_quota": True})
    return err


class Fake:
    """A provider whose behaviour per model is scripted: an exception to raise or a text to return."""

    def __init__(self, name: str, script: dict[str, Any] | None = None) -> None:
        self.name = name
        self.script = script or {}
        self.calls: list[tuple[str, str]] = []

    def _do(self, op: str, model: str) -> Any:
        self.calls.append((op, model))
        outcome = self.script.get(model, json.dumps({"answer": model}))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def complete(self, *, model: str, system: str, user: str, max_tokens: int, timeout: int, json_mode: bool, **_: Any) -> ProviderResponse:
        return ProviderResponse(text=self._do("complete", model), model=model, prompt_tokens=10, completion_tokens=5)

    def create_with_tools(self, *, model: str, messages: list[dict[str, Any]], **_: Any) -> Any:
        self.calls.append(("history", messages))  # type: ignore[arg-type]
        self._do("tools", model)
        block = SimpleNamespace(type="text", text=f"answer from {model}", model_dump=lambda **__: {"type": "text", "text": f"answer from {model}"})
        return SimpleNamespace(content=[block], stop_reason="end_turn", model=model, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


@pytest.fixture(autouse=True)
def _fresh_health():
    HEALTH.reset()
    yield
    HEALTH.reset()


def test_retry_hint_parsing_and_cooldowns():
    assert retry_after_seconds("Please retry in 13h8m51.8s.") == pytest.approx(13 * 3600 + 8 * 60 + 51.8)
    assert retry_after_seconds("retry in 37s") == 37
    assert retry_after_seconds("no hint here") is None
    assert cooldown_for(quota_error()) == (2 * 3600 + 3 * 60 + 4, "quota exhausted")
    overloaded = LLMError("Gemini API error 503: high demand", details={"status": 503})
    assert cooldown_for(overloaded)[1] == "unavailable"
    bad = LLMError("bad request", details={"status": 400})
    bad.retryable = False
    assert cooldown_for(bad) is None  # not an availability problem: never fail over


def test_quota_on_primary_fails_over_and_the_route_rests():
    gem = Fake("gemini", {"gemini-a": quota_error()})
    claude = Fake("anthropic")
    fo = FailoverProvider([Route(gem, "gemini-a", "gemini-a"), Route(gem, "gemini-b", "gemini-b"), Route(claude, "claude-sonnet-5-5", "claude-haiku-5-5")])
    gw = LLMGateway(provider=fo, settings=Settings(_env_file=None))
    out, usage = gw.structured(task="t", schema=Out, system="s", user="u", heuristic=lambda: {"answer": "rules"})
    assert out.answer == "gemini-b" and usage.provider == "gemini"  # next Gemini model (own free quota)
    assert fo.status()["routes"][0]["state"] == "cooling" and fo.status()["routes"][0]["reason"] == "quota exhausted"
    gem.calls.clear()
    gw.structured(task="t", schema=Out, system="s", user="u", heuristic=lambda: {"answer": "rules"})
    assert [m for _, m in gem.calls] == ["gemini-b"]  # the resting route is skipped, not retried


def test_all_routes_down_means_instant_builtin_logic(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(g.time, "sleep", lambda s: sleeps.append(s))
    gem = Fake("gemini", {"gemini-a": quota_error(), "gemini-b": quota_error()})
    fo = FailoverProvider([Route(gem, "gemini-a", "gemini-a"), Route(gem, "gemini-b", "gemini-b")])
    gw = LLMGateway(provider=fo, settings=Settings(_env_file=None))
    out, usage = gw.structured(task="t", schema=Out, system="s", user="u", heuristic=lambda: {"answer": "rules"})
    assert out.answer == "rules" and usage.model == "heuristic-fallback"
    assert sleeps == []  # no pointless retries against providers known to be out of quota
    status = fo.status()
    assert status["available"] is False and status["next_available_at"]
    assert gw.copilot_mode == "offline_planner"


def test_non_availability_errors_are_not_masked():
    bad = LLMError("Gemini declined this request", details={"provider": "gemini"})
    bad.retryable = False
    gem, claude = Fake("gemini", {"gemini-a": bad}), Fake("anthropic")
    fo = FailoverProvider([Route(gem, "gemini-a", "gemini-a"), Route(claude, "claude-sonnet-5-5", "claude-haiku-5-5")])
    with pytest.raises(LLMError, match="declined"):
        fo.complete(model="gemini-a", system="s", user="u", max_tokens=10, timeout=5, json_mode=True)
    assert claude.calls == []


def test_tier_and_override_mapping():
    gem, claude = Fake("gemini"), Fake("anthropic", {"claude-sonnet-5-5": quota_error("anthropic")})
    fo = FailoverProvider([Route(gem, "gemini-pro", "gemini-flash"), Route(claude, "claude-sonnet-5-5", "claude-haiku-5-5")])
    fo.complete(model="gemini-flash", system="s", user="u", max_tokens=10, timeout=5, json_mode=False)
    assert gem.calls[-1] == ("complete", "gemini-flash")
    HEALTH.cool("gemini:gemini-pro", 60, "unavailable")
    fo.complete(model="gemini-flash", system="s", user="u", max_tokens=10, timeout=5, json_mode=False)
    assert claude.calls[-1] == ("complete", "claude-haiku-5-5")  # fast tier maps to the fast model
    HEALTH.reset()
    fo.complete(model="claude-opus-5-5", system="s", user="u", max_tokens=10, timeout=5, json_mode=False)
    assert claude.calls[-1] == ("complete", "claude-opus-5-5")  # an agent's model override goes first


def _tools() -> list[LoopTool]:
    return [LoopTool(name="noop", description="d", input_schema={"type": "object", "properties": {}}, kind="tool", label="Noop", run=lambda _: ToolOutcome(content={}))]


class _Recorder:
    def started(self, *a: Any) -> None:
        return None

    def finished(self, *a: Any) -> None:
        return None


class _Planner:
    def plan(self, user_text: str, done: list, iteration: int, tools: dict) -> list:
        return []

    def answer(self, user_text: str, done: list) -> str:
        return "offline answer"


def test_copilot_fails_over_with_a_clean_history_for_claude():
    gem = Fake("gemini", {"gemini-a": LLMError("Gemini API error 503: overloaded", details={"status": 503})})
    claude = Fake("anthropic")
    fo = FailoverProvider([Route(gem, "gemini-a", "gemini-a"), Route(claude, "claude-sonnet-5-5", "claude-haiku-5-5")])
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": [{"type": "tool_use", "id": "x", "name": "noop", "input": {}, "thought_signature": "c2ln"}, {"type": "text", "text": "", "thought_signature": "c2ln"}]}, {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "{}"}]}]
    result = run_tool_loop(gateway=LLMGateway(provider=fo, settings=Settings(_env_file=None)), system="s", history=history, user_text="now", tools=_tools(), observer=_Recorder(), planner=_Planner())
    assert result.text == "answer from claude-sonnet-5-5" and result.model == "claude-sonnet-5-5"
    sent = next(m for op, m in claude.calls if op == "history")
    assistant_blocks = sent[1]["content"]
    assert all("thought_signature" not in b for b in assistant_blocks) and len(assistant_blocks) == 1  # signature-only text dropped


def test_copilot_answers_offline_when_no_ai_is_available():
    gem = Fake("gemini", {"gemini-a": quota_error()})
    fo = FailoverProvider([Route(gem, "gemini-a", "gemini-a"), Route(gem, "gemini-b", "gemini-b")])
    HEALTH.cool("gemini:gemini-b", 60, "quota exhausted")
    result = run_tool_loop(gateway=LLMGateway(provider=fo, settings=Settings(_env_file=None)), system="s", history=[], user_text="hi", tools=_tools(), observer=_Recorder(), planner=_Planner())
    assert result.mode == "offline_planner" and result.text == "offline answer" and AI_UNAVAILABLE_WARNING in result.warnings


def test_settings_auto_provider_and_route_building():
    s = Settings(_env_file=None, llm_provider="auto", anthropic_api_key="a", gemini_api_key="g", llm_default_model="claude-opus-5-5", llm_fast_model="claude-opus-5-5")
    assert s.effective_llm_provider == "gemini" and s.llm_fallback_list == ["anthropic"]
    assert s.models_for("gemini") == ("gemini-3.6-flash", "gemini-3.6-flash")  # LLM_DEFAULT_MODEL is a Claude id
    routes = g.build_routes(s)
    assert [r.key for r in routes] == ["gemini:gemini-3.6-flash", "gemini:gemini-3.8-flash", "gemini:gemini-3.5-flash-lite", "anthropic:claude-sonnet-5-5"]
    assert Settings(_env_file=None, llm_provider="auto").effective_llm_provider == "mock"
    none = Settings(_env_file=None, llm_provider="gemini", gemini_api_key="g", anthropic_api_key="a", llm_fallback_providers="none", gemini_fallback_models="")
    assert isinstance(g.build_provider(none), g.GeminiProvider)  # one route: no wrapper
