"""Typed tool registry.

A *tool* is a named, typed capability backed by an integration adapter method
(or a platform-internal service). Tools are the only way agents and the action
executor touch the outside world. Each tool declares:

* `provider`   - which adapter family fulfils it (crm, email, slack, ...) or "platform"
* `side_effect`- True => may change external state; agents may only *propose* it
* `idempotent` - whether a repeat with the same idempotency key is safe
* `required_permission` - the caller (actor + agent) must hold this scope
* `risk_level` - informs the policy engine's approval decision
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    key: str
    name: str
    description: str
    provider: str
    method: str
    side_effect: bool = False
    idempotent: bool = True
    required_permission: str
    risk_level: str = "low"
    input_model: type[BaseModel] | None = None
    verify_method: str | None = None  # adapter method used to reconcile unknown outcomes
    external_ref_field: str | None = None  # field in the response that identifies the external object

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "provider": self.provider,
            "side_effect": self.side_effect,
            "idempotent": self.idempotent,
            "required_permission": self.required_permission,
            "risk_level": self.risk_level,
            "input_schema": self.input_model.model_json_schema() if self.input_model else {},
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.key in self._tools:
            raise ValueError(f"Tool '{spec.key}' already registered")
        self._tools[spec.key] = spec
        return spec

    def get(self, key: str) -> ToolSpec:
        try:
            return self._tools[key]
        except KeyError as exc:
            raise KeyError(f"Unknown tool '{key}'") from exc

    def has(self, key: str) -> bool:
        return key in self._tools

    def all(self) -> list[ToolSpec]:
        return sorted(self._tools.values(), key=lambda t: t.key)

    def by_provider(self, provider: str) -> list[ToolSpec]:
        return [t for t in self.all() if t.provider == provider]

    def validate_payload(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        spec = self.get(key)
        if spec.input_model is None:
            return payload
        return spec.input_model.model_validate(payload).model_dump(mode="json", exclude_none=True)


tool_registry = ToolRegistry()


def tool(**kwargs: Any) -> ToolSpec:
    return tool_registry.register(ToolSpec(**kwargs))


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="allow")


class FreeformInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    note: str | None = Field(default=None, description="Optional free-form note")
