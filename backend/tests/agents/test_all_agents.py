"""Per-agent tests: registration contract, invalid input rejection, synthetic evaluation datasets,
and output-contract validation for every one of the 25 agents."""

import pytest
from pydantic import ValidationError

from app.agents.registry import agent_registry
from app.agents.runner import run_agent
from app.core.errors import ValidationFailed
from app.evaluation.datasets import DATASETS
from app.evaluation.harness import run_evaluation
from app.tools.registry import tool_registry

AGENT_KEYS = sorted(a.spec.key for a in agent_registry.all())
EXPECTED = {
    "lead_qualification", "sales_development", "sales_call_intelligence", "proposal_generator",
    "customer_support", "complaint_resolution", "whatsapp_business", "customer_retention",
    "shopping_assistant", "order_management", "inventory_forecasting", "product_listing",
    "workflow_coordinator", "meeting_to_execution", "sop_compliance", "business_intelligence",
    "invoice_processing", "expense_audit", "payment_followup", "procurement",
    "qa_testing", "bug_triage", "product_research", "release_monitoring", "finance_analyst",
}


def test_all_25_registered():
    assert set(AGENT_KEYS) == EXPECTED and len(AGENT_KEYS) == 25


@pytest.mark.parametrize("key", AGENT_KEYS)
def test_contract(key):
    spec = agent_registry.get(key).spec
    assert spec.name and spec.description and spec.version and spec.department
    assert spec.input_model.model_json_schema()["properties"] is not None
    assert spec.output_model.model_json_schema()["properties"]
    for t in spec.allowed_tools:
        assert tool_registry.has(t), f"{key} references unknown tool {t}"
        ts = tool_registry.get(t)
        assert ts.required_permission in spec.permission_scopes or ts.provider == "platform" or any(ts.required_permission.split(":")[0] == p.split(":")[0] for p in spec.permission_scopes), f"{key}: tool {t} needs {ts.required_permission}"
    assert key in DATASETS and DATASETS[key]["cases"], f"{key} has no evaluation dataset"
    assert spec.timeout_seconds > 0 and spec.token_budget > 0 and spec.baseline_minutes_saved >= 0


@pytest.mark.parametrize("key", AGENT_KEYS)
def test_invalid_input_rejected(key, db, demo_tenant):
    agent = agent_registry.get(key)
    with pytest.raises(ValidationError):
        agent.validate_input({"__definitely_not_a_field__": object()})  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        run_agent(db, tenant=demo_tenant, agent_key=key, input={"__bad__": {"x": object()}}, actor_id="t", permissions=["*"], correlation_id="c", execute_actions=False)


@pytest.mark.parametrize("key", AGENT_KEYS)
def test_evaluation_dataset_passes(key, db, demo_tenant):
    result = run_evaluation(db, demo_tenant, key)
    failing = [c for c in result.case_results if not c["passed"]]
    assert result.passed, f"{key} failing cases: {[(c['name'], [ch for ch in c['checks'] if not ch['passed']]) for c in failing]}"
    assert result.metrics["unsupported_claim_rate"] <= 0.5
    assert result.metrics["cost_per_case_usd"] == 0.0  # mock provider


def test_runner_validates_output_against_contract(db, demo_tenant, monkeypatch):
    from app.agents.base import AgentResult
    from app.agents.catalog.d13_workflow_coordinator import WorkflowCoordinatorAgent

    def bad_run(self, ctx, payload, services):
        return AgentResult(status="completed", data={"garbage": True})

    monkeypatch.setattr(WorkflowCoordinatorAgent, "run", bad_run)
    with pytest.raises(ValidationFailed):
        run_agent(db, tenant=demo_tenant, agent_key="workflow_coordinator", input={}, actor_id="t", permissions=["*"], correlation_id="c")
