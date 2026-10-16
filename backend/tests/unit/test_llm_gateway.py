import pytest
from pydantic import BaseModel

from app.core.errors import LLMError, LLMOutputInvalid, QuotaExceeded
from app.llm.gateway import BudgetTracker, LLMGateway, MockProvider, ProviderResponse, estimate_cost


class Out(BaseModel):
    answer: str
    score: int


class FlakyProvider:
    name = "flaky"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def complete(self, **kw):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return ProviderResponse(text=r, model="test-model", prompt_tokens=10, completion_tokens=5)


def test_mock_uses_heuristic_and_zero_cost():
    gw = LLMGateway(provider=MockProvider())
    out, usage = gw.structured(task="t", schema=Out, system="s", user="u", heuristic=lambda: {"answer": "a", "score": 1})
    assert out.answer == "a" and usage.model == "mock-heuristic" and usage.cost_usd == 0


def test_mock_without_heuristic_fails_loudly():
    with pytest.raises(LLMOutputInvalid):
        LLMGateway(provider=MockProvider()).structured(task="t", schema=Out, system="s", user="u")


def test_parses_json_in_code_fence_and_retries_invalid():
    p = FlakyProvider(["not json", '```json\n{"answer":"ok","score":2}\n```'])
    out, usage = LLMGateway(provider=p).structured(task="t", schema=Out, system="s", user="u")
    assert out.score == 2 and p.calls == 2 and usage.cost_usd > 0


def test_falls_back_to_heuristic_after_provider_errors_and_marks_model():
    err = LLMError("down")
    p = FlakyProvider([err, err, err])
    gw = LLMGateway(provider=p)
    gw.max_retries = 2
    budget = BudgetTracker(token_budget=10_000)
    out, usage = gw.structured(task="t", schema=Out, system="s", user="u", heuristic=lambda: Out(answer="h", score=0), budget=budget)
    assert out.answer == "h" and usage.model == "heuristic-fallback" and budget.warnings


def test_schema_violation_without_heuristic_raises():
    p = FlakyProvider(['{"answer":"x"}', '{"answer":"x"}', '{"answer":"x"}'])
    with pytest.raises(LLMOutputInvalid):
        LLMGateway(provider=p).structured(task="t", schema=Out, system="s", user="u")


def test_budget_enforced():
    b = BudgetTracker(token_budget=5)
    with pytest.raises(QuotaExceeded):
        LLMGateway(provider=MockProvider()).structured(task="t", schema=Out, system="s" * 100, user="u" * 100, heuristic=lambda: {"answer": "a", "score": 1}, budget=b)


def test_cost_estimate_uses_table():
    assert estimate_cost("claude-haiku-5-5", 1_000_000, 0) == 0.1
    assert estimate_cost("claude-opus-5-5", 1_000_000, 1_000_000) == 24.0
    assert estimate_cost("mock-heuristic", 100, 100) == 0
