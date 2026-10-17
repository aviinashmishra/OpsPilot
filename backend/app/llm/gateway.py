"""Provider-agnostic LLM gateway with structured output validation, token
budgets, timeouts, cost tracking and a deterministic mock provider.

Design
------
Agents call `gateway.structured(...)` with:
  * a Pydantic schema the answer must satisfy,
  * a system prompt (trusted) and user content (untrusted data wrapped by the caller),
  * a `heuristic` callable: a deterministic implementation that produces an
    acceptable answer from the input without any model. It is used (a) by the
    mock provider so the whole platform runs offline, and (b) as a graceful
    fallback when a provider call fails after retries - in which case the result
    is explicitly marked `model="heuristic-fallback"` and a warning is attached.

Nothing in this module grants permissions or executes actions.
"""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.errors import LLMError, LLMOutputInvalid, QuotaExceeded
from app.core.logging import get_logger

log = get_logger("llm")
T = TypeVar("T", bound=BaseModel)

# USD per 1M tokens (input, output), first-party list prices as of 2026-10.
# Edit this table if your contract or platform (Bedrock / Vertex) prices differ.
DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    # Gemini Developer API standard rates; introductory rates are lower until the dates noted.
    "gemini-4-argon": (4.0, 20.0),  # $2 / $10 through 2026-11-30
    "gemini-3.8-flash": (1.50, 7.50),  # $0.75 / $3.75 through 2026-12-31
    "gemini-3.6-flash": (1.50, 7.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "mock-heuristic": (0.0, 0.0),
    "heuristic-fallback": (0.0, 0.0),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    inp, out = DEFAULT_PRICING.get(model, (3.0, 15.0))
    return round((prompt_tokens * inp + completion_tokens * out) / 1_000_000, 6)


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


_RETRY_IN = re.compile(r"retry in\s+(?:(\d+)h)?\s*(?:(\d+)m(?!s))?\s*(?:([\d.]+)s)?", re.I)


def retry_after_seconds(message: str) -> float | None:
    """Parse "Please retry in 13h8m51.8s" / "retry in 37s" from a provider error message."""
    m = _RETRY_IN.search(message or "")
    if not m or not any(m.groups()):
        return None
    hours, minutes, seconds = (float(g) if g else 0.0 for g in m.groups())
    return hours * 3600 + minutes * 60 + seconds


def _header_retry_after(exc: Any) -> float | None:
    try:
        value = exc.response.headers.get("retry-after")
        return float(value) if value else None
    except (AttributeError, TypeError, ValueError):
        return None


@dataclass
class ProviderResponse:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int


class LLMProvider(Protocol):
    name: str

    def complete(self, *, model: str, system: str, user: str, max_tokens: int, timeout: int, json_mode: bool, **kwargs: Any) -> ProviderResponse: ...


@dataclass
class LLMUsage:
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    provider: str = "mock"
    calls: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "provider": self.provider,
            "calls": self.calls,
        }


@dataclass
class BudgetTracker:
    token_budget: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0
    latency_ms: int = 0
    models: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def record(self, usage: LLMUsage) -> None:
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens
        self.cost_usd = round(self.cost_usd + usage.cost_usd, 6)
        self.calls += 1
        self.latency_ms += usage.latency_ms
        if usage.model not in self.models:
            self.models.append(usage.model)

    def check(self, upcoming_prompt_tokens: int) -> None:
        if self.total_tokens + upcoming_prompt_tokens > self.token_budget:
            raise QuotaExceeded(
                "Agent token budget exceeded",
                details={"budget": self.token_budget, "used": self.total_tokens, "upcoming": upcoming_prompt_tokens},
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": self.cost_usd,
            "calls": self.calls,
            "latency_ms": self.latency_ms,
            "models": self.models,
        }


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


class MockProvider:
    """Deterministic provider for local development and tests.

    It never calls a network. `structured()` detects this provider and runs the
    caller-supplied heuristic instead; `complete()` returns a canned JSON that
    validates as an empty object so misuse fails loudly at schema validation.
    """

    name = "mock"

    def complete(self, *, model: str, system: str, user: str, max_tokens: int, timeout: int, json_mode: bool) -> ProviderResponse:
        return ProviderResponse(text="{}", model="mock-heuristic", prompt_tokens=approx_tokens(system + user), completion_tokens=1)


class SchemaUnsupported(Exception):
    """The provider rejected a JSON schema for native structured output; use JSON prompting instead."""


FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    """Claude via the official `anthropic` SDK (1.x).

    * Native structured outputs (`beta.messages.parse(output_format=<pydantic model>)`)
      with a JSON-prompting fallback for schemas the API rejects.
    * Thinking is left at the model default (Claude Opus 5.5 always thinks; depth is
      controlled with `output_config.effort`).
    * Server-side refusal fallbacks are enabled (`fallbacks="default"`) so a request
      declined by a safety classifier is retried on an appropriate model; a final
      `stop_reason == "refusal"` is surfaced as a non-retryable LLMError.
    * The system prompt (and the tool list in tool loops) carries `cache_control`
      so repeated calls reuse the cached prefix.
    """

    name = "anthropic"

    def __init__(self, api_key: str, *, enable_fallbacks: bool = True) -> None:
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=2)
        self._fallback_kwargs: dict[str, Any] = {"betas": [FALLBACK_BETA], "fallbacks": "default"} if enable_fallbacks else {}

    @staticmethod
    def _system(system: str) -> list[dict[str, Any]]:
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    def _map_error(self, exc: Exception) -> Exception:
        a = self._anthropic
        if isinstance(exc, a.RateLimitError):
            return LLMError("Anthropic rate limit", details={"provider": "anthropic", "status": 429, "retry_after_s": _header_retry_after(exc)})
        if isinstance(exc, a.BadRequestError):
            err = LLMError(f"Anthropic rejected the request: {getattr(exc, 'message', exc)}", details={"provider": "anthropic", "status": 400})
            err.retryable = False
            return err
        if isinstance(exc, a.APIStatusError):
            err = LLMError(f"Anthropic API error: {exc.status_code}", details={"provider": "anthropic", "status": exc.status_code})
            err.retryable = exc.status_code >= 500 or exc.status_code in {408, 409}
            return err
        if isinstance(exc, a.APIConnectionError):
            return LLMError("Anthropic connection error", details={"provider": "anthropic"})
        return exc

    @staticmethod
    def _check_stop(msg: Any) -> None:
        if getattr(msg, "stop_reason", None) == "refusal":
            details = getattr(msg, "stop_details", None)
            err = LLMError("Claude declined this request", details={"provider": "anthropic", "category": getattr(details, "category", None)})
            err.retryable = False
            raise err

    def complete(self, *, model: str, system: str, user: str, max_tokens: int, timeout: int, json_mode: bool, effort: str | None = None) -> ProviderResponse:
        try:
            msg = self._client.beta.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=self._system(system + ("\nRespond with a single JSON object and nothing else." if json_mode else "")),
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort} if effort else self._anthropic.omit,
                timeout=timeout,
                **self._fallback_kwargs,
            )
        except self._anthropic.APIError as exc:
            raise self._map_error(exc) from exc
        self._check_stop(msg)
        text = "".join(block.text for block in msg.content if block.type == "text")
        return ProviderResponse(text=text, model=msg.model, prompt_tokens=msg.usage.input_tokens, completion_tokens=msg.usage.output_tokens)

    def parse(self, *, model: str, system: str, user: str, schema: type[T], max_tokens: int, timeout: int, effort: str | None = None) -> tuple[T, ProviderResponse]:
        try:
            msg = self._client.beta.messages.parse(
                model=model,
                max_tokens=max_tokens,
                system=self._system(system),
                messages=[{"role": "user", "content": user}],
                output_format=schema,
                output_config={"effort": effort} if effort else self._anthropic.omit,
                timeout=timeout,
                **self._fallback_kwargs,
            )
        except self._anthropic.BadRequestError as exc:
            # Most often a schema feature structured outputs does not support (e.g. free-form dicts).
            raise SchemaUnsupported(str(getattr(exc, "message", exc))) from exc
        except self._anthropic.APIError as exc:
            raise self._map_error(exc) from exc
        except TypeError as exc:  # schema the SDK cannot transform locally
            raise SchemaUnsupported(str(exc)) from exc
        self._check_stop(msg)
        if msg.stop_reason == "max_tokens":
            raise LLMOutputInvalid("Structured output truncated at max_tokens")
        parsed = getattr(msg, "parsed_output", None)
        if parsed is None:
            raise LLMOutputInvalid("Claude returned no parsable structured output")
        text = "".join(block.text for block in msg.content if block.type == "text")
        return parsed, ProviderResponse(text=text, model=msg.model, prompt_tokens=msg.usage.input_tokens, completion_tokens=msg.usage.output_tokens)

    def create_with_tools(self, *, model: str, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int, timeout: int, effort: str | None = None) -> Any:
        """One Messages API call in an agentic tool loop. Returns the SDK message."""
        cached_tools = [dict(t) for t in tools]
        if cached_tools:
            cached_tools[-1]["cache_control"] = {"type": "ephemeral"}  # caches the whole tool list + system prefix
        try:
            msg = self._client.beta.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=self._system(system),
                tools=cached_tools,
                messages=messages,
                output_config={"effort": effort} if effort else self._anthropic.omit,
                timeout=timeout,
                **self._fallback_kwargs,
            )
        except self._anthropic.APIError as exc:
            raise self._map_error(exc) from exc
        self._check_stop(msg)
        return msg


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)

    def complete(self, *, model: str, system: str, user: str, max_tokens: int, timeout: int, json_mode: bool) -> ProviderResponse:
        import openai

        try:
            resp = self._client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=max_tokens,
                timeout=timeout,
                response_format={"type": "json_object"} if json_mode else None,  # type: ignore[arg-type]
            )
        except openai.RateLimitError as exc:
            raise LLMError("OpenAI rate limit", details={"provider": "openai", "status": 429, "retry_after_s": _header_retry_after(exc)}) from exc
        except openai.APIStatusError as exc:
            err = LLMError(f"OpenAI API error: {exc.status_code}", details={"provider": "openai"})
            err.retryable = exc.status_code >= 500
            raise err from exc
        except openai.APIConnectionError as exc:
            raise LLMError("OpenAI connection error", details={"provider": "openai"}) from exc
        choice = resp.choices[0]
        usage = resp.usage
        return ProviderResponse(
            text=choice.message.content or "",
            model=resp.model,
            prompt_tokens=usage.prompt_tokens if usage else approx_tokens(system + user),
            completion_tokens=usage.completion_tokens if usage else approx_tokens(choice.message.content or ""),
        )


# OpsPilot effort -> Gemini thinking level. Gemini 3.x/4 accept low|medium|high ("minimal" errors on some models).
GEMINI_THINKING_LEVELS = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "xhigh": "HIGH", "max": "HIGH"}
_GEMINI_BLOCKED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}
_GEMINI_LOCAL_ID = "gcall_"  # ids we mint when the model returns a function call without one


@dataclass
class _Block:
    """Anthropic-shaped content block, so the tool loop and stored Copilot history stay provider-neutral."""

    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None
    thought_signature: str | None = None  # base64; Gemini needs it back verbatim on the next request

    def model_dump(self, **_: Any) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class _ToolTurn:
    content: list[_Block]
    stop_reason: str
    model: str
    usage: Any


class GeminiProvider:
    """Gemini via Google's official `google-genai` SDK (Gemini Developer API key).

    * Native structured outputs (`response_json_schema`) with the gateway's JSON-prompting fallback.
    * Effort maps to `thinking_level`; thinking tokens are billed (and counted here) as output.
    * `create_with_tools` speaks the tool loop's Anthropic block format: history is converted to
      Gemini `Content` on the way in and the reply back into text / tool_use blocks, carrying
      Gemini's thought signatures along so they can be returned on the next call.
    """

    name = "gemini"

    def __init__(self, api_key: str) -> None:
        from google import genai
        from google.genai import errors, types

        self._types = types
        self._errors = errors
        self._client = genai.Client(api_key=api_key)

    # -- request plumbing -------------------------------------------------
    def _config(self, *, model: str, system: str, max_tokens: int, timeout: int, effort: str | None, **extra: Any) -> Any:
        t = self._types
        thinking = None
        if effort in GEMINI_THINKING_LEVELS and not model.startswith(("gemini-1", "gemini-2")):  # older models use budgets
            thinking = t.ThinkingConfig(thinking_level=t.ThinkingLevel(GEMINI_THINKING_LEVELS[effort]))
        return t.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens, thinking_config=thinking, http_options=t.HttpOptions(timeout=timeout * 1000), **extra)

    def _generate(self, *, model: str, contents: Any, config: Any) -> Any:
        import httpx

        try:
            resp = self._client.models.generate_content(model=model, contents=contents, config=config)
        except self._errors.APIError as exc:
            raise self._map_error(exc) from exc
        except httpx.HTTPError as exc:
            raise LLMError("Gemini connection error", details={"provider": "gemini"}) from exc
        self._check_blocked(resp)
        return resp

    @staticmethod
    def _map_error(exc: Any) -> LLMError:
        code = getattr(exc, "code", None) or 0
        details: dict[str, Any] = {"provider": "gemini", "status": code}
        full = str(exc)  # parsed before truncation: the "retry in ..." hint sits at the end
        if code == 429:
            details["retry_after_s"] = retry_after_seconds(full)
            details["daily_quota"] = "per_day" in full.lower() or "free_tier_requests" in full.lower()
        err = LLMError(f"Gemini API error {code}: {getattr(exc, 'message', None) or exc}"[:500], details=details)
        err.retryable = code == 429 or code >= 500 or code in {408, 409}
        return err

    @staticmethod
    def _check_blocked(resp: Any) -> None:
        if not resp.candidates:
            reason = getattr(getattr(resp, "prompt_feedback", None), "block_reason", None)
            err = LLMError("Gemini returned no candidates", details={"provider": "gemini", "block_reason": str(reason) if reason else None})
            err.retryable = reason is None
            raise err
        finish = GeminiProvider._finish(resp)
        if finish in _GEMINI_BLOCKED:
            err = LLMError("Gemini declined this request", details={"provider": "gemini", "finish_reason": finish})
            err.retryable = False
            raise err

    @staticmethod
    def _finish(resp: Any) -> str:
        reason = resp.candidates[0].finish_reason
        return getattr(reason, "value", None) or str(reason or "")

    @staticmethod
    def _parts(resp: Any) -> list[Any]:
        content = resp.candidates[0].content
        return [p for p in (content.parts or []) if not p.thought] if content else []

    @staticmethod
    def _tokens(resp: Any) -> tuple[int, int, int]:
        u = resp.usage_metadata
        if u is None:
            return 0, 0, 0
        return u.prompt_token_count or 0, (u.candidates_token_count or 0) + (u.thoughts_token_count or 0), u.cached_content_token_count or 0

    def _response(self, resp: Any, model: str) -> ProviderResponse:
        prompt, completion, _ = self._tokens(resp)
        text = "".join(p.text for p in self._parts(resp) if p.text)
        return ProviderResponse(text=text, model=resp.model_version or model, prompt_tokens=prompt, completion_tokens=completion)

    # -- gateway API --------------------------------------------------------
    def complete(self, *, model: str, system: str, user: str, max_tokens: int, timeout: int, json_mode: bool, effort: str | None = None) -> ProviderResponse:
        config = self._config(model=model, system=system, max_tokens=max_tokens, timeout=timeout, effort=effort, response_mime_type="application/json" if json_mode else None)
        return self._response(self._generate(model=model, contents=user, config=config), model)

    def parse(self, *, model: str, system: str, user: str, schema: type[T], max_tokens: int, timeout: int, effort: str | None = None) -> tuple[T, ProviderResponse]:
        config = self._config(model=model, system=system, max_tokens=max_tokens, timeout=timeout, effort=effort, response_mime_type="application/json", response_json_schema=schema.model_json_schema())
        try:
            resp = self._generate(model=model, contents=user, config=config)
        except LLMError as exc:
            if exc.details.get("status") == 400:  # most often a schema feature Gemini does not accept
                raise SchemaUnsupported(str(exc)) from exc
            raise
        if self._finish(resp) == "MAX_TOKENS":
            raise LLMOutputInvalid("Structured output truncated at max_output_tokens (thinking counts toward it)")
        out = self._response(resp, model)
        try:
            return schema.model_validate_json(out.text), out
        except ValidationError as exc:
            raise LLMOutputInvalid("Gemini returned no parsable structured output", details={"errors": exc.errors()[:5]}) from exc

    def create_with_tools(self, *, model: str, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int, timeout: int, effort: str | None = None) -> _ToolTurn:
        """One generate_content call in the agentic tool loop, returned as an Anthropic-shaped message."""
        t = self._types
        declarations = [t.FunctionDeclaration(name=d["name"], description=d.get("description", ""), parameters_json_schema=d.get("input_schema") or {"type": "object", "properties": {}}) for d in tools]
        config = self._config(model=model, system=system, max_tokens=max_tokens, timeout=timeout, effort=effort, tools=[t.Tool(function_declarations=declarations)] if declarations else None)
        resp = self._generate(model=model, contents=self.to_contents(messages), config=config)
        finish = self._finish(resp)
        if finish == "MALFORMED_FUNCTION_CALL":
            raise LLMError("Gemini produced a malformed function call", details={"provider": "gemini", "finish_reason": finish})
        blocks: list[_Block] = []
        for part in self._parts(resp):
            sig = base64.b64encode(part.thought_signature).decode() if part.thought_signature else None
            if part.function_call is not None:
                fc = part.function_call
                blocks.append(_Block("tool_use", id=fc.id or f"{_GEMINI_LOCAL_ID}{uuid.uuid4().hex[:12]}", name=fc.name, input=dict(fc.args or {}), thought_signature=sig))
            elif part.text is not None or sig:
                blocks.append(_Block("text", text=part.text or "", thought_signature=sig))
        stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "max_tokens" if finish == "MAX_TOKENS" else "end_turn"
        prompt, completion, cached = self._tokens(resp)
        usage = SimpleNamespace(input_tokens=prompt, output_tokens=completion, cache_read_input_tokens=cached, cache_creation_input_tokens=0)
        return _ToolTurn(content=blocks, stop_reason=stop, model=resp.model_version or model, usage=usage)

    def to_contents(self, messages: list[dict[str, Any]]) -> list[Any]:
        """Anthropic-format history (as stored by the tool loop) -> Gemini Content list."""
        t = self._types
        names: dict[str, str] = {}  # tool_use id -> function name (Gemini responses are matched by id AND name)
        contents = []
        for m in messages:
            blocks = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
            parts = []
            for b in blocks:
                kind = b.get("type")
                sig = base64.b64decode(b["thought_signature"]) if b.get("thought_signature") else None
                if kind == "text" and (b.get("text") or sig):
                    parts.append(t.Part(text=b.get("text") or "", thought_signature=sig))
                elif kind == "tool_use":
                    names[b["id"]] = b["name"]
                    parts.append(t.Part(function_call=t.FunctionCall(id=self._wire_id(b["id"]), name=b["name"], args=b.get("input") or {}), thought_signature=sig))
                elif kind == "tool_result":
                    call_id = b["tool_use_id"]
                    parts.append(t.Part(function_response=t.FunctionResponse(id=self._wire_id(call_id), name=names.get(call_id, "unknown_tool"), response=self._result_payload(b))))
                # thinking / redacted_thinking blocks from a Claude-written history have no Gemini equivalent
            if parts:
                contents.append(t.Content(role="model" if m["role"] == "assistant" else "user", parts=parts))
        return contents

    @staticmethod
    def _wire_id(call_id: str) -> str | None:
        return None if call_id.startswith(_GEMINI_LOCAL_ID) else call_id

    @staticmethod
    def _result_payload(block: dict[str, Any]) -> dict[str, Any]:
        content = block.get("content")
        if isinstance(content, list):
            content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        try:
            value = json.loads(content) if isinstance(content, str) else content
        except json.JSONDecodeError:
            value = content
        return {"error" if block.get("is_error") else "output": value}


def _make_provider(name: str, s: Settings) -> Any:
    if name == "anthropic":
        return AnthropicProvider(s.anthropic_api_key or "", enable_fallbacks=s.llm_enable_fallbacks)
    if name == "openai":
        return OpenAIProvider(s.openai_api_key or "")
    return GeminiProvider(s.gemini_api_key or "")


def build_routes(s: Settings) -> list[Any]:
    """Primary route first, then extra Gemini models, then the other keyed providers."""
    from app.llm.failover import Route

    primary = s.effective_llm_provider
    if primary == "mock":
        return []
    routes: list[Route] = []
    for name in [primary, *s.llm_fallback_list]:
        provider = _make_provider(name, s)
        default, fast = s.models_for(name)
        routes.append(Route(provider, default, fast))
        if name == "gemini":
            for extra in (m.strip() for m in s.gemini_fallback_models.split(",")):
                if extra and extra not in (default, fast):
                    routes.append(Route(provider, extra, extra))
    return routes


def build_provider(settings: Settings | None = None) -> LLMProvider:
    """A single provider, a FailoverProvider over several routes, or the offline mock."""
    from app.llm.failover import FailoverProvider

    s = settings or get_settings()
    routes = build_routes(s)
    if not routes:
        if s.llm_provider != "mock":
            log.warning("llm.provider_unconfigured", provider=s.llm_provider, fallback="mock")
        return MockProvider()
    return routes[0].provider if len(routes) == 1 else FailoverProvider(routes)


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_BLOCK.search(text)
        if not m:
            raise
        return json.loads(m.group(0))


class LLMGateway:
    def __init__(self, provider: LLMProvider | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.provider = provider or build_provider(self.settings)
        self.max_retries = 2
        self._schema_unsupported: set[str] = set()

    @property
    def is_mock(self) -> bool:
        return self.provider.name == "mock"

    @property
    def failover(self) -> Any:
        """The FailoverProvider when several routes are configured, else None."""
        return self.provider if self.provider.name == "failover" else None

    @property
    def copilot_mode(self) -> str:
        """Which model family drives the Copilot tool loop now, or the offline planner when none can."""
        if self.is_mock or not hasattr(self.provider, "create_with_tools"):
            return "offline_planner"
        name = self.provider.name
        if self.failover is not None:
            route = self.failover.active_route(tools=True)
            if route is None:
                return "offline_planner"
            name = route.provider.name
        return "claude" if name == "anthropic" else name

    def ai_status(self) -> dict[str, Any]:
        """Provider/route availability for the dashboard."""
        if self.failover is not None:
            return self.failover.status()
        if self.is_mock:
            return {"available": False, "active": None, "next_available_at": None, "routes": []}
        default, fast = self.resolve_model("default"), self.resolve_model("fast")
        return {"available": True, "active": {"provider": self.provider.name, "model": default}, "next_available_at": None, "routes": [{"provider": self.provider.name, "model": default, "fast_model": fast, "tools": hasattr(self.provider, "create_with_tools"), "state": "ready", "until": None, "reason": None}]}

    def resolve_model(self, tier: str = "default", override: str | None = None) -> str:
        if override:
            return override
        if self.failover is not None:
            route = self.failover.primary
            return route.fast_model if tier == "fast" else route.default_model
        default, fast = self.settings.llm_default_model, self.settings.llm_fast_model
        from app.llm.failover import model_family

        if not self.is_mock and model_family(default) not in (None, self.provider.name):
            default, fast = self.settings.models_for(self.provider.name)  # e.g. LLM_PROVIDER=auto picked another family
        return fast if tier == "fast" else default

    @property
    def _usage_provider(self) -> str:
        return getattr(self.provider, "last_used", None) or self.provider.name

    def resolve_effort(self, tier: str = "default") -> str:
        return self.settings.llm_fast_effort if tier == "fast" else self.settings.llm_effort

    def structured(
        self,
        *,
        task: str,
        schema: type[T],
        system: str,
        user: str,
        heuristic: Callable[[], T | dict[str, Any]] | None = None,
        budget: BudgetTracker | None = None,
        model: str | None = None,
        tier: str = "default",
        max_tokens: int | None = None,
        force_heuristic: bool = False,
    ) -> tuple[T, LLMUsage]:
        """Return a validated `schema` instance plus usage. Deterministic under the mock provider."""
        started = time.perf_counter()
        user = user[: self.settings.llm_max_input_chars]
        prompt_tokens_est = approx_tokens(system + user)
        if budget:
            budget.check(prompt_tokens_est)

        if self.is_mock or force_heuristic:
            if heuristic is None:
                raise LLMOutputInvalid(f"No heuristic available for task '{task}' under mock provider")
            result = self._validate(schema, heuristic(), task)
            usage = LLMUsage(
                model="mock-heuristic",
                prompt_tokens=prompt_tokens_est,
                completion_tokens=approx_tokens(result.model_dump_json()),
                cost_usd=0.0,
                latency_ms=int((time.perf_counter() - started) * 1000),
                provider="mock",
                calls=1,
            )
            if budget:
                budget.record(usage)
            return result, usage

        schema_hint = json.dumps(schema.model_json_schema(), separators=(",", ":"))
        full_system = (
            f"{system}\n\nYou must answer with one JSON object that validates against this JSON schema:\n{schema_hint}\n"
            "Never invent facts that are not supported by the provided data. If information is missing, say so in the designated fields."
        )
        resolved_model = self.resolve_model(tier, model)
        effort = self.resolve_effort(tier)
        last_error: Exception | None = None
        native = getattr(self.provider, "parse", None)
        if native is not None and schema.__name__ not in self._schema_unsupported:
            for attempt in range(self.max_retries + 1):
                try:
                    parsed_obj, resp = native(model=resolved_model, system=system + "\nNever invent facts that are not supported by the provided data. If information is missing, say so in the designated fields.", user=user, schema=schema, max_tokens=max_tokens or self.settings.llm_max_output_tokens, timeout=self.settings.llm_timeout_seconds, effort=effort)
                    result = self._validate(schema, parsed_obj, task)
                    usage = LLMUsage(model=resp.model, prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens, cost_usd=estimate_cost(resp.model, resp.prompt_tokens, resp.completion_tokens), latency_ms=int((time.perf_counter() - started) * 1000), provider=self._usage_provider, calls=attempt + 1)
                    if budget:
                        budget.record(usage)
                    return result, usage
                except SchemaUnsupported as exc:
                    log.info("llm.schema_unsupported_for_native_output", task=task, schema=schema.__name__, error=str(exc)[:200])
                    self._schema_unsupported.add(schema.__name__)
                    break
                except LLMOutputInvalid as exc:
                    last_error = exc
                    log.warning("llm.invalid_output", task=task, attempt=attempt, error=str(exc)[:300])
                except LLMError as exc:
                    last_error = exc
                    log.warning("llm.provider_error", task=task, attempt=attempt, error=str(exc))
                    if not exc.retryable:
                        return self._fallback(task, schema, heuristic, budget, last_error, started, prompt_tokens_est)
                    time.sleep(min(2**attempt * 0.5, 4))
            else:
                return self._fallback(task, schema, heuristic, budget, last_error, started, prompt_tokens_est)
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.provider.complete(
                    model=resolved_model,
                    system=full_system,
                    user=user,
                    max_tokens=max_tokens or self.settings.llm_max_output_tokens,
                    timeout=self.settings.llm_timeout_seconds,
                    json_mode=True,
                    **({"effort": effort} if self.provider.name in ("anthropic", "gemini", "failover") else {}),
                )
                parsed = _extract_json(resp.text)
                result = self._validate(schema, parsed, task)
                usage = LLMUsage(
                    model=resp.model,
                    prompt_tokens=resp.prompt_tokens,
                    completion_tokens=resp.completion_tokens,
                    cost_usd=estimate_cost(resp.model, resp.prompt_tokens, resp.completion_tokens),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    provider=self._usage_provider,
                    calls=attempt + 1,
                )
                if budget:
                    budget.record(usage)
                return result, usage
            except (LLMOutputInvalid, json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                log.warning("llm.invalid_output", task=task, attempt=attempt, error=str(exc)[:300])
                user = user + "\n\nYour previous answer was not valid JSON for the schema. Return only the JSON object."
            except LLMError as exc:
                last_error = exc
                log.warning("llm.provider_error", task=task, attempt=attempt, error=str(exc))
                if not exc.retryable:
                    break
                time.sleep(min(2**attempt * 0.5, 4))
        return self._fallback(task, schema, heuristic, budget, last_error, started, prompt_tokens_est)

    def _fallback(self, task: str, schema: type[T], heuristic: Callable[[], T | dict[str, Any]] | None, budget: BudgetTracker | None, last_error: Exception | None, started: float, prompt_tokens_est: int) -> tuple[T, LLMUsage]:
        if heuristic is not None:
            log.warning("llm.fallback_to_heuristic", task=task, error=str(last_error)[:200])
            result = self._validate(schema, heuristic(), task)
            usage = LLMUsage(
                model="heuristic-fallback",
                prompt_tokens=prompt_tokens_est,
                completion_tokens=approx_tokens(result.model_dump_json()),
                latency_ms=int((time.perf_counter() - started) * 1000),
                provider=self.provider.name,
                calls=self.max_retries + 1,
            )
            if budget:
                budget.record(usage)
                budget.warnings.append(f"LLM call for '{task}' failed ({type(last_error).__name__}); deterministic fallback used")
            return result, usage
        raise LLMOutputInvalid(f"LLM failed to produce valid output for '{task}'", details={"error": str(last_error)})

    @staticmethod
    def _validate(schema: type[T], raw: Any, task: str) -> T:
        if isinstance(raw, schema):
            return raw
        if isinstance(raw, BaseModel):
            raw = raw.model_dump()
        try:
            return schema.model_validate(raw)
        except ValidationError as exc:
            raise LLMOutputInvalid(f"Output for '{task}' failed validation", details={"errors": exc.errors()[:5]}) from exc


_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway


def reset_gateway() -> None:
    global _gateway
    _gateway = None
