"""Agent registry: discovery, catalog sync and lookup."""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

from app.agents.base import AgentSpec, BaseAgent


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, type[BaseAgent]] = {}
        self._loaded = False

    def register(self, agent_cls: type[BaseAgent]) -> type[BaseAgent]:
        key = agent_cls.spec.key
        if key in self._agents and self._agents[key] is not agent_cls:
            raise ValueError(f"Agent '{key}' already registered")
        self._agents[key] = agent_cls
        return agent_cls

    def load_builtin(self) -> None:
        """Import every module under app.agents.catalog so their @register decorators run."""
        if self._loaded:
            return
        import app.agents.catalog as catalog_pkg

        for mod in pkgutil.iter_modules(catalog_pkg.__path__):
            importlib.import_module(f"{catalog_pkg.__name__}.{mod.name}")
        self._loaded = True

    def get(self, key: str) -> type[BaseAgent]:
        self.load_builtin()
        try:
            return self._agents[key]
        except KeyError as exc:
            raise KeyError(f"Unknown agent '{key}'") from exc

    def has(self, key: str) -> bool:
        self.load_builtin()
        return key in self._agents

    def all(self) -> list[type[BaseAgent]]:
        self.load_builtin()
        return sorted(self._agents.values(), key=lambda a: a.spec.key)

    def specs(self) -> list[AgentSpec]:
        return [a.spec for a in self.all()]

    def catalog(self) -> list[dict[str, Any]]:
        return [a.spec.to_catalog_dict() for a in self.all()]


agent_registry = AgentRegistry()

# Platform actors that are not catalog agents (e.g. the Ops Copilot) but propose actions
# through the same policy/approval machinery.
_platform_specs: dict[str, AgentSpec] = {}


def register_platform_spec(spec: AgentSpec) -> AgentSpec:
    _platform_specs[spec.key] = spec
    return spec


def resolve_spec(key: str | None) -> AgentSpec | None:
    if not key:
        return None
    if agent_registry.has(key):
        return agent_registry.get(key).spec
    if key not in _platform_specs:
        import app.copilot.spec  # noqa: F401 - registers the copilot spec lazily
    return _platform_specs.get(key)


def register(agent_cls: type[BaseAgent]) -> type[BaseAgent]:
    return agent_registry.register(agent_cls)
