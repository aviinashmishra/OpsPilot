"""The Copilot's own agent spec (used by the policy engine and approvals)."""

from __future__ import annotations

from pydantic import BaseModel

from app.agents.base import AgentSpec, ApprovalRule
from app.agents.registry import register_platform_spec

# Read-only integration tools the Copilot may call directly. Side-effecting work is
# always delegated to a specialist agent (whose proposals are policy-gated) or to a
# custom tool, whose side effects go through the approval center.
COPILOT_READ_TOOLS: list[str] = [
    "crm.list_leads", "crm.get_lead", "crm.find_lead", "crm.list_customers", "crm.get_customer",
    "commerce.search_products", "commerce.price_and_stock", "commerce.get_order", "commerce.get_shipment", "commerce.list_orders", "commerce.list_inventory",
    "accounting.list_invoices", "accounting.get_invoice", "accounting.list_expense_claims",
    "helpdesk.list_tickets", "issues.search", "monitoring.get_deployments", "monitoring.get_metrics",
    "metrics.list", "metrics.query", "feedback.list", "procurement.list_quotes",
    "workspace.list_employees", "workspace.directory_lookup",
    "platform.list_tasks", "platform.search_knowledge", "platform.workflow_usage",
]


class _Empty(BaseModel):
    pass


COPILOT_SPEC = register_platform_spec(
    AgentSpec(
        key="ops_copilot",
        name="Ops Copilot",
        department="operations",
        version="1.0.0",
        description="Conversational orchestrator that plans and calls the specialist agents and tools on the user's behalf.",
        input_model=_Empty,
        output_model=_Empty,
        allowed_tools=[*COPILOT_READ_TOOLS, "custom.*"],
        permission_scopes=["agents:run"],
        policies=["delegates_side_effects_to_policy_gated_agents", "custom_tool_side_effects_require_approval"],
        approval_rules=[ApprovalRule(action_type="custom.*", condition="side-effecting custom HTTP tools", required_permission="approvals:decide")],
        risk_level="medium",
    )
)
