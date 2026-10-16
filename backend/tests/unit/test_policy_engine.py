from pydantic import BaseModel

from app.agents.base import AgentContext, AgentSpec, ApprovalRule, ProposedAction
from app.policy.engine import POLICY_VERSION, evaluate_action, evaluate_agent_enabled


class _M(BaseModel):
    pass


def _spec(tools: list[str], rules: list[ApprovalRule] | None = None) -> AgentSpec:
    return AgentSpec(key="t", name="t", department="operations", description="d", input_model=_M, output_model=_M, allowed_tools=tools, approval_rules=rules or [])


def _ctx(perms: list[str]) -> AgentContext:
    return AgentContext(tenant_id="00000000-0000-0000-0000-000000000001", actor_id="u", correlation_id="c", permissions=perms)


def test_read_only_tool_allowed():
    d = evaluate_action(ctx=_ctx(["crm:read"]), agent_spec=_spec(["crm.find_lead"]), action=ProposedAction(action_type="x", tool_key="crm.find_lead"))
    assert d.outcome == "allow" and d.policy_version == POLICY_VERSION


def test_tool_not_in_allowlist_denied():
    d = evaluate_action(ctx=_ctx(["*"]), agent_spec=_spec(["crm.find_lead"]), action=ProposedAction(action_type="x", tool_key="email.send"))
    assert d.outcome == "deny" and d.policy_id == "platform.tool_allowlist"


def test_unknown_tool_denied():
    d = evaluate_action(ctx=_ctx(["*"]), agent_spec=_spec(["nope.tool"]), action=ProposedAction(action_type="x", tool_key="nope.tool"))
    assert d.outcome == "deny"


def test_missing_permission_on_read_tool_denied():
    d = evaluate_action(ctx=_ctx(["email:read"]), agent_spec=_spec(["crm.find_lead"]), action=ProposedAction(action_type="x", tool_key="crm.find_lead"))
    assert d.outcome == "deny" and d.policy_id == "platform.permission"


def test_missing_permission_on_side_effect_requires_reviewer_with_permission():
    d = evaluate_action(ctx=_ctx(["crm:read"]), agent_spec=_spec(["crm.upsert_lead"]), action=ProposedAction(action_type="x", tool_key="crm.upsert_lead"))
    assert d.outcome == "require_approval" and d.required_permission == "crm:write"


def test_external_email_requires_approval_by_default():
    d = evaluate_action(ctx=_ctx(["*"]), agent_spec=_spec(["email.send"]), action=ProposedAction(action_type="email.send", tool_key="email.send", payload={"to": "a@b.c"}))
    assert d.outcome == "require_approval"


def test_narrow_auto_approve_policy_allows_email():
    settings = {"policies": {"auto_approve": [{"name": "receipts", "tool": "email.send", "conditions": {"template_id_in": ["TPL-RECEIPT"]}}]}}
    allowed = evaluate_action(ctx=_ctx(["*"]), agent_spec=_spec(["email.send"]), action=ProposedAction(action_type="email.send", tool_key="email.send", payload={"to": "a@b.c", "template_id": "TPL-RECEIPT"}), tenant_settings=settings)
    blocked = evaluate_action(ctx=_ctx(["*"]), agent_spec=_spec(["email.send"]), action=ProposedAction(action_type="email.send", tool_key="email.send", payload={"to": "a@b.c", "template_id": "OTHER"}), tenant_settings=settings)
    assert allowed.outcome == "allow" and blocked.outcome == "require_approval"


def test_critical_tool_cannot_be_auto_approved():
    settings = {"policies": {"auto_approve": [{"tool": "*", "conditions": {}}]}}
    d = evaluate_action(ctx=_ctx(["*"]), agent_spec=_spec(["procurement.create_purchase_order"]), action=ProposedAction(action_type="po", tool_key="procurement.create_purchase_order", payload={"total": 5}), tenant_settings=settings)
    assert d.outcome == "require_approval" and d.policy_id == "platform.critical_risk"


def test_amount_threshold():
    d = evaluate_action(ctx=_ctx(["*"]), agent_spec=_spec(["helpdesk.create_ticket"]), action=ProposedAction(action_type="t", tool_key="helpdesk.create_ticket", payload={"subject": "x", "description": "y", "amount": 5000}), tenant_settings={"policies": {"amount_threshold": 1000}})
    assert d.outcome == "require_approval" and d.policy_id == "tenant.amount_threshold"


def test_strict_mode_gates_everything():
    d = evaluate_action(ctx=_ctx(["*"]), agent_spec=_spec(["helpdesk.create_ticket"]), action=ProposedAction(action_type="t", tool_key="helpdesk.create_ticket", payload={"subject": "x", "description": "y"}), tenant_settings={"policies": {"approval_mode": "strict"}})
    assert d.outcome == "require_approval" and d.policy_id == "tenant.strict_mode"


def test_agent_approval_rule():
    spec = _spec(["crm.log_activity"], [ApprovalRule(action_type="crm.*")])
    d = evaluate_action(ctx=_ctx(["*"]), agent_spec=spec, action=ProposedAction(action_type="crm.log_activity", tool_key="crm.log_activity", payload={"lead_id": "1", "activity_type": "a", "note": "n"}))
    assert d.outcome == "require_approval"


def test_emergency_disable_denies_all():
    d = evaluate_action(ctx=_ctx(["*"]), agent_spec=_spec(["crm.find_lead"]), action=ProposedAction(action_type="x", tool_key="crm.find_lead"), emergency_disabled=True)
    assert d.outcome == "deny"


def test_denied_tools_tenant_policy():
    d = evaluate_action(ctx=_ctx(["*"]), agent_spec=_spec(["chat.post_message"]), action=ProposedAction(action_type="x", tool_key="chat.post_message", payload={"channel": "#a", "text": "t"}), tenant_settings={"policies": {"denied_tools": ["chat.post_message"]}})
    assert d.outcome == "deny"


def test_agent_enabled_matrix():
    assert evaluate_agent_enabled(globally_enabled=True, tenant_enabled=None, emergency_disabled=False)[0]
    assert not evaluate_agent_enabled(globally_enabled=False, tenant_enabled=True, emergency_disabled=False)[0]
    assert not evaluate_agent_enabled(globally_enabled=True, tenant_enabled=False, emergency_disabled=False)[0]
    assert not evaluate_agent_enabled(globally_enabled=True, tenant_enabled=True, emergency_disabled=True)[0]
