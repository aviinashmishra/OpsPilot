"""GeminiProvider, driven by a fake google-genai client (no network, no key).

Verifies the conversion contract with the tool loop: Gemini function calls come back
as Anthropic-shaped tool_use blocks, the stored history is replayed as Gemini contents
(function responses matched by id and name, thought signatures returned verbatim),
plus structured output, error mapping and the effective-provider label.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors, types
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import LLMError
from app.llm import gateway as g
from app.llm.gateway import GeminiProvider, LLMGateway
from app.llm.tool_loop import run_tool_loop
from tests.unit.test_tool_loop import NoPlanner, Recorder, _tools

SIG = b"\x01opaque-signature"


def reply(parts: list[types.Part], finish: str = "STOP") -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts), finish_reason=types.FinishReason(finish))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=20, thoughts_token_count=30, cached_content_token_count=60),
        model_version="gemini-4-argon",
    )


class FakeModels:
    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    def generate_content(self, **kw: Any) -> Any:
        self.requests.append(kw)
        nxt = self.script.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def provider(script: list[Any]) -> tuple[GeminiProvider, FakeModels]:
    p = GeminiProvider.__new__(GeminiProvider)
    p._types, p._errors = types, errors
    models = FakeModels(script)
    p._client = SimpleNamespace(models=models)
    return p, models


def test_tool_loop_round_trip_converts_both_ways():
    p, models = provider([
        reply([
            types.Part(text="Checking both."),
            types.Part(function_call=types.FunctionCall(id="fc_1", name="get_stock", args={"sku": "A"}), thought_signature=SIG),
            types.Part(function_call=types.FunctionCall(name="broken", args={})),  # no id: we mint a local one
        ]),
        reply([types.Part(text="A has 3 on hand; the other lookup failed.")]),
    ])
    result = run_tool_loop(gateway=LLMGateway(provider=p), system="sys", history=[], user_text="check", tools=_tools(), observer=Recorder(), planner=NoPlanner(), effort="high")
    assert result.mode == "gemini" and result.text.startswith("A has 3") and result.tool_calls == 2
    # Stored history keeps the Anthropic block shape (plus the signature for replay).
    assistant = result.new_history[1]["content"]
    assert [b["type"] for b in assistant] == ["text", "tool_use", "tool_use"] and assistant[1]["thought_signature"]
    assert assistant[2]["id"].startswith("gcall_")
    assert result.usage["output_tokens"] == 100 and result.usage["cache_read_input_tokens"] == 120 and result.usage["cost_usd"] > 0

    first = models.requests[0]["config"]
    assert first.system_instruction == "sys" and first.thinking_config.thinking_level == types.ThinkingLevel.HIGH
    assert [d.name for d in first.tools[0].function_declarations] == ["get_stock", "broken"]
    assert first.tools[0].function_declarations[0].parameters_json_schema["required"] == ["sku"]

    sent = models.requests[1]["contents"]
    assert [c.role for c in sent] == ["user", "model", "user"]
    call = sent[1].parts[1]
    assert call.function_call.id == "fc_1" and call.thought_signature == SIG  # returned verbatim
    assert sent[1].parts[2].function_call.id is None  # locally minted ids never go on the wire
    responses = [part.function_response for part in sent[2].parts]
    assert len(responses) == 2  # all results in one user turn
    assert responses[0].id == "fc_1" and responses[0].name == "get_stock" and responses[0].response == {"output": {"sku": "A", "on_hand": 3}}
    assert responses[1].name == "broken" and "upstream exploded" in str(responses[1].response["error"])


def test_claude_written_history_replays_without_thinking_blocks():
    p, _ = provider([])
    prior = [{"role": "user", "content": "first"}, {"role": "assistant", "content": [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": "first answer"}]}]
    contents = p.to_contents(prior + [{"role": "user", "content": "again"}])
    assert [(c.role, [part.text for part in c.parts]) for c in contents] == [("user", ["first"]), ("model", ["first answer"]), ("user", ["again"])]


class Answer(BaseModel):
    label: str
    score: float


def test_structured_output_and_schema_fallback():
    p, models = provider([reply([types.Part(text='{"label": "ok", "score": 0.9}')])])
    parsed, resp = p.parse(model="gemini-3.8-flash", system="s", user="u", schema=Answer, max_tokens=4096, timeout=30, effort="low")
    assert parsed == Answer(label="ok", score=0.9) and resp.completion_tokens == 50
    cfg = models.requests[0]["config"]
    assert cfg.response_mime_type == "application/json" and cfg.response_json_schema["required"] == ["label", "score"]
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.LOW and cfg.http_options.timeout == 30_000

    p, _ = provider([errors.ClientError(400, {"error": {"code": 400, "message": "schema too complex", "status": "INVALID_ARGUMENT"}})])
    with pytest.raises(g.SchemaUnsupported):
        p.parse(model="gemini-3.8-flash", system="s", user="u", schema=Answer, max_tokens=4096, timeout=30)

    p, _ = provider([reply([types.Part(text='{"label": "o')], finish="MAX_TOKENS")])
    with pytest.raises(g.LLMOutputInvalid):
        p.parse(model="gemini-3.8-flash", system="s", user="u", schema=Answer, max_tokens=64, timeout=30)


def test_error_mapping_and_safety_blocks():
    p, _ = provider([errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})])
    with pytest.raises(LLMError) as exc:
        p.complete(model="gemini-4-argon", system="s", user="u", max_tokens=100, timeout=10, json_mode=True)
    assert exc.value.retryable is True and exc.value.details["status"] == 429

    p, _ = provider([reply([], finish="SAFETY")])
    with pytest.raises(LLMError) as exc:
        p.complete(model="gemini-4-argon", system="s", user="u", max_tokens=100, timeout=10, json_mode=False)
    assert exc.value.retryable is False and exc.value.details["finish_reason"] == "SAFETY"

    p, models = provider([reply([types.Part(text="hi")])])
    p.complete(model="gemini-2.5-flash", system="s", user="u", max_tokens=100, timeout=10, json_mode=False, effort="high")
    assert models.requests[0]["config"].thinking_config is None  # 2.x models take budgets, not levels


@pytest.mark.parametrize(("name", "key_field", "cls"), [("anthropic", "anthropic_api_key", g.AnthropicProvider), ("openai", "openai_api_key", g.OpenAIProvider), ("gemini", "gemini_api_key", GeminiProvider)])
def test_real_sdk_clients_construct_offline(name, key_field, cls):
    """Catches SDK/httpx pin drift (e.g. openai<1.55 passing `proxies` to httpx 0.28) without any network call."""
    provider = g.build_provider(Settings(_env_file=None, llm_provider=name, **{key_field: "test-key"}))
    assert isinstance(provider, cls) and provider.name == name


def test_effective_provider_and_validation():
    s = Settings(_env_file=None, llm_provider="gemini", gemini_api_key=None)
    assert s.effective_llm_provider == "mock" and "LLM_PROVIDER=gemini requires GEMINI_API_KEY" in s.validate_for_environment()
    s = Settings(_env_file=None, llm_provider="gemini", gemini_api_key="k", llm_default_model="gemini-4-argon", llm_fast_model="claude-opus-5-5")
    assert s.effective_llm_provider == "gemini"
    assert [p for p in s.validate_for_environment() if "LLM_FAST_MODEL" in p]
    assert LLMGateway(provider=g.MockProvider()).copilot_mode == "offline_planner"
