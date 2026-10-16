"""The operational CLI runs against the seeded demo tenant."""

import json

from app.cli import main

LEAD = {"lead": {"name": "CLI Lead", "email": "cli@globex.test", "company": "Globex", "title": "CTO", "company_size": 600, "budget": 50000, "timeline": "this quarter", "message": "We need automation."}}


def test_run_workflow_defaults_to_demo_tenant(capsys):
    main(["run-workflow", "lead_to_crm", "--input", json.dumps(LEAD)])
    out = json.loads(capsys.readouterr().out)
    assert out["status"] in {"waiting_approval", "completed"} and out["error"] is None
