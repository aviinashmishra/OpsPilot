"""Deterministic policy engine.

Decides, for each proposed action, one of: allow | require_approval | deny.
Rules are ordered and evaluated in plain Python; the model has no influence over
the outcome beyond the content of the proposed action itself. Tenant
administrators can tighten (never loosen below platform floors) behaviour via
`tenant.settings["policies"]`.

Tenant policy settings (all optional):
    approval_mode:            "standard" | "strict"   (strict => every side effect needs approval)
    amount_threshold:         float  (payload amounts above this need approval; default 1000)
    auto_approve:             list of {tool, conditions:{template_id_in?, max_recipients?, channel_in?}}
    denied_tools:             list of tool keys that are always denied
    external_comms_require_approval: bool (default True)
"""

from __future__ import annotations

import fnmatch
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentSpec, ProposedAction
from app.tools.registry import ToolSpec, tool_registry

POLICY_VERSION = "2026.10.v1"

EXTERNAL_COMM_TOOLS = {"email.send", "whatsapp.send_template", "whatsapp.send_text"}
ALWAYS_APPROVE_RISK = {"critical"}
AMOUNT_FIELDS = ("amount", "total", "total_amount", "grand_total", "value")


class PolicyDecision(BaseModel):
    outcome: Literal["allow", "require_approval", "deny"]
    reason: str
    policy_id: str
    required_permission: str = "approvals:decide"
    risk_level: str = "medium"
    policy_version: str = POLICY_VERSION
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.outcome == "allow"


def _find_amount(payload: dict[str, Any]) -> float | None:
    stack: list[Any] = [payload]
    best: float | None = None
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in AMOUNT_FIELDS and isinstance(v, int | float):
                    best = max(best or 0.0, float(v))
                elif isinstance(v, dict | list):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return best


def _auto_approve_matches(rule: dict[str, Any], tool_key: str, payload: dict[str, Any]) -> bool:
    if not fnmatch.fnmatch(tool_key, str(rule.get("tool", ""))):
        return False
    cond = rule.get("conditions") or {}
    if "template_id_in" in cond:
        tid = payload.get("template_id") or payload.get("template_name")
        if tid not in cond["template_id_in"]:
            return False
    if "channel_in" in cond and payload.get("channel") not in cond["channel_in"]:
        return False
    if "max_amount" in cond:
        amt = _find_amount(payload)
        if amt is not None and amt > float(cond["max_amount"]):
            return False
    return True


def tool_allowed(agent_spec: AgentSpec, tool_key: str) -> bool:
    """Exact keys or glob patterns (e.g. ``custom.*``) from the agent's allowlist."""
    return any(tool_key == pat or ("*" in pat and fnmatch.fnmatchcase(tool_key, pat)) for pat in agent_spec.allowed_tools)


def evaluate_action(
    *,
    ctx: AgentContext,
    agent_spec: AgentSpec,
    action: ProposedAction,
    tenant_settings: dict[str, Any] | None = None,
    emergency_disabled: bool = False,
    tool_spec: ToolSpec | None = None,
) -> PolicyDecision:
    """`tool_spec` lets callers pass specs for tenant-defined tools that are not in the global registry."""
    policies = (tenant_settings or {}).get("policies", {}) or {}
    tool_key = action.tool_key

    # 0. Platform floors ------------------------------------------------------
    if emergency_disabled:
        return PolicyDecision(outcome="deny", reason="Tenant is in emergency-disabled state", policy_id="platform.emergency_disable", risk_level="critical")
    if tool_spec is None and not tool_registry.has(tool_key):
        return PolicyDecision(outcome="deny", reason=f"Unknown tool '{tool_key}'", policy_id="platform.unknown_tool", risk_level="high")
    spec: ToolSpec = tool_spec or tool_registry.get(tool_key)
    if not tool_allowed(agent_spec, tool_key):
        return PolicyDecision(outcome="deny", reason=f"Agent '{agent_spec.key}' is not allowed to use '{tool_key}'", policy_id="platform.tool_allowlist", risk_level="high", details={"tool": tool_key})
    if tool_key in set(policies.get("denied_tools", []) or []):
        return PolicyDecision(outcome="deny", reason="Tool denied by tenant policy", policy_id="tenant.denied_tools", risk_level=spec.risk_level)
    if not spec.side_effect:
        if not ctx.has_permission(spec.required_permission):
            return PolicyDecision(outcome="deny", reason=f"Actor lacks permission '{spec.required_permission}'", policy_id="platform.permission", required_permission=spec.required_permission, risk_level=spec.risk_level)
        return PolicyDecision(outcome="allow", reason="Read-only tool", policy_id="platform.read_only", risk_level="low")

    if not ctx.has_permission(spec.required_permission):
        # The requester may propose, but only a reviewer holding the permission may execute.
        return PolicyDecision(outcome="require_approval", reason=f"Requester lacks '{spec.required_permission}'; a reviewer holding it must approve", policy_id="platform.permission_escalation", required_permission=spec.required_permission, risk_level=max_risk(spec.risk_level, action.risk_level))

    # 1. Hard approval requirements ----------------------------------------------
    if spec.risk_level in ALWAYS_APPROVE_RISK:
        return PolicyDecision(outcome="require_approval", reason="Critical-risk action always requires human approval", policy_id="platform.critical_risk", required_permission=spec.required_permission, risk_level="critical")
    if action.requires_approval is True:
        return PolicyDecision(outcome="require_approval", reason="Agent explicitly requested approval", policy_id="agent.explicit", required_permission="approvals:decide", risk_level=action.risk_level)
    for rule in agent_spec.approval_rules:
        if fnmatch.fnmatch(action.action_type, rule.action_type) or fnmatch.fnmatch(tool_key, rule.action_type):
            if rule.always:
                return PolicyDecision(outcome="require_approval", reason=f"Agent approval rule '{rule.action_type}'" + (f": {rule.condition}" if rule.condition else ""), policy_id=f"agent.{agent_spec.key}.approval_rule", required_permission=rule.required_permission, risk_level=max_risk(spec.risk_level, action.risk_level))

    amount = _find_amount(action.payload)
    threshold = float(policies.get("amount_threshold", 1000))
    if amount is not None and amount > threshold:
        return PolicyDecision(outcome="require_approval", reason=f"Amount {amount:.2f} exceeds approval threshold {threshold:.2f}", policy_id="tenant.amount_threshold", required_permission="approvals:decide", risk_level="high", details={"amount": amount, "threshold": threshold})

    # 2. External communications ------------------------------------------------
    if tool_key in EXTERNAL_COMM_TOOLS and policies.get("external_comms_require_approval", True):
        for rule in policies.get("auto_approve", []) or []:
            if _auto_approve_matches(rule, tool_key, action.payload):
                return PolicyDecision(outcome="allow", reason=f"Narrow auto-approve policy matched ({rule.get('name', rule.get('tool'))})", policy_id="tenant.auto_approve", risk_level=spec.risk_level, details={"rule": rule})
        return PolicyDecision(outcome="require_approval", reason="External customer communication requires approval", policy_id="platform.external_comms", required_permission=spec.required_permission, risk_level="high")

    # 3. Risk-based ----------------------------------------------------------------
    if spec.risk_level == "high" or action.risk_level in {"high", "critical"}:
        for rule in policies.get("auto_approve", []) or []:
            if _auto_approve_matches(rule, tool_key, action.payload):
                return PolicyDecision(outcome="allow", reason="Narrow auto-approve policy matched", policy_id="tenant.auto_approve", risk_level=spec.risk_level, details={"rule": rule})
        return PolicyDecision(outcome="require_approval", reason="High-risk action requires approval", policy_id="platform.high_risk", required_permission=spec.required_permission, risk_level="high")
    if policies.get("approval_mode") == "strict":
        return PolicyDecision(outcome="require_approval", reason="Tenant policy: strict approval mode", policy_id="tenant.strict_mode", required_permission="approvals:decide", risk_level=spec.risk_level)

    return PolicyDecision(outcome="allow", reason="Low/medium-risk internal action permitted by policy", policy_id="platform.default_allow", risk_level=spec.risk_level)


_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def max_risk(a: str, b: str) -> str:
    return a if _RISK_ORDER.get(a, 1) >= _RISK_ORDER.get(b, 1) else b


def evaluate_agent_enabled(*, globally_enabled: bool, tenant_enabled: bool | None, emergency_disabled: bool) -> tuple[bool, str]:
    if emergency_disabled:
        return False, "tenant emergency disable is active"
    if not globally_enabled:
        return False, "agent is disabled platform-wide"
    if tenant_enabled is False:
        return False, "agent is disabled for this tenant"
    return True, "enabled"
