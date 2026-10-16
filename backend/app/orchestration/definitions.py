"""Built-in workflow templates (tenant_id = NULL => available to every tenant).

Each graph is explicit, bounded and inspectable in the dashboard's workflow
viewer. Agents only ever appear as `agent` nodes; routing, gating and
delegation are deterministic nodes.
"""

from __future__ import annotations

from typing import Any

BUILTIN_WORKFLOWS: list[dict[str, Any]] = [
    {
        "key": "lead_to_crm",
        "name": "New lead → qualified CRM record → outreach draft",
        "description": "Normalises and scores an inbound lead, writes it to the CRM, and (for qualified leads) drafts a personalised outreach that waits for human approval before sending.",
        "trigger": {"event_types": ["lead.created", "form.submitted"], "source": "any"},
        "timeout_seconds": 600,
        "graph": {
            "start": "qualify",
            "nodes": {
                "qualify": {"type": "agent", "agent": "lead_qualification", "input": {"lead": "$.input.lead", "source": "$.input.source"}, "next": "is_qualified", "on_failure": "end"},
                "is_qualified": {"type": "condition", "when": {"path": "$.nodes.qualify.data.qualified", "equals": True}, "then": "outreach", "else": "end"},
                "outreach": {"type": "agent", "agent": "sales_development", "input": {"lead_id": "$.nodes.qualify.data.lead_id", "lead": "$.nodes.qualify.data.normalized_lead", "qualification": "$.nodes.qualify.data"}, "next": "gate"},
                "gate": {"type": "approval_gate", "next": "end"},
                "end": {"type": "end"},
            },
        },
    },
    {
        "key": "meeting_to_tasks",
        "name": "Meeting transcript → tasks → coordinator",
        "description": "Extracts decisions and action items from an authorised transcript, resolves owners via the directory, creates tasks, then lets the coordinator check for blockers and overdue work.",
        "trigger": {"event_types": ["meeting.transcript_ready"]},
        "timeout_seconds": 600,
        "graph": {
            "start": "extract",
            "nodes": {
                "extract": {"type": "agent", "agent": "meeting_to_execution", "input": {"meeting_id": "$.input.meeting_id", "transcript": "$.input.transcript", "title": "$.input.title", "attendees": "$.input.attendees"}, "next": "coordinate", "on_needs_input": "end"},
                "coordinate": {"type": "agent", "agent": "workflow_coordinator", "input": {"scope": "recent", "source_run_id": "$.run.id"}, "next": "gate"},
                "gate": {"type": "approval_gate", "next": "end"},
                "end": {"type": "end"},
            },
        },
    },
    {
        "key": "customer_query",
        "name": "Customer question → verified, cited answer",
        "description": "Answers from the authorised knowledge base and account data with citations; escalates to a complaint ticket when the query is a complaint or unsupported.",
        "trigger": {"event_types": ["support.message_received"]},
        "timeout_seconds": 300,
        "graph": {
            "start": "answer",
            "nodes": {
                "answer": {"type": "agent", "agent": "customer_support", "input": {"message": "$.input.message", "customer_id": "$.input.customer_id", "channel": "$.input.channel", "order_id": "$.input.order_id"}, "next": "is_complaint"},
                "is_complaint": {"type": "condition", "when": {"path": "$.nodes.answer.data.is_complaint", "equals": True}, "then": "complaint", "else": "end"},
                "complaint": {"type": "agent", "agent": "complaint_resolution", "input": {"message": "$.input.message", "customer_id": "$.input.customer_id", "channel": "$.input.channel", "order_id": "$.input.order_id"}, "next": "end"},
                "end": {"type": "end"},
            },
        },
    },
    {
        "key": "whatsapp_inbound",
        "name": "WhatsApp message → intent → compliant reply",
        "description": "Handles inbound WhatsApp messages (verified webhook) with opt-in, 24h-window and template rules; replies are approval-gated unless a narrow tenant policy auto-approves them.",
        "trigger": {"event_types": ["whatsapp.message_received"]},
        "timeout_seconds": 120,
        "graph": {
            "start": "handle",
            "nodes": {
                "handle": {"type": "agent", "agent": "whatsapp_business", "input": {"phone": "$.input.phone", "message": "$.input.message", "customer_id": "$.input.customer_id", "message_id": "$.input.message_id", "profile_name": "$.input.profile_name"}, "next": "gate"},
                "gate": {"type": "approval_gate", "next": "end"},
                "end": {"type": "end"},
            },
        },
    },
    {
        "key": "invoice_to_review",
        "name": "Invoice → 3-way match → review request",
        "description": "Extracts invoice fields, matches PO and receipts, validates arithmetic, detects duplicates and stages a payable for human approval. Never pays.",
        "trigger": {"event_types": ["invoice.received"]},
        "timeout_seconds": 300,
        "graph": {
            "start": "process",
            "nodes": {
                "process": {"type": "agent", "agent": "invoice_processing", "input": {"document_text": "$.input.document_text", "document_id": "$.input.document_id", "vendor_hint": "$.input.vendor_hint"}, "next": "gate"},
                "gate": {"type": "approval_gate", "next": "end"},
                "end": {"type": "end"},
            },
        },
    },
    {
        "key": "overdue_escalation",
        "name": "Overdue tasks → approved escalation",
        "description": "The coordinator finds overdue work deterministically and proposes escalations that require approval before owners are notified.",
        "trigger": {"schedule": "hourly"},
        "timeout_seconds": 300,
        "graph": {
            "start": "coordinate",
            "nodes": {
                "coordinate": {"type": "agent", "agent": "workflow_coordinator", "input": {"scope": "overdue"}, "next": "gate"},
                "gate": {"type": "approval_gate", "next": "end"},
                "end": {"type": "end"},
            },
        },
    },
    {
        "key": "kpi_report",
        "name": "KPI data → evidence-backed report",
        "description": "Business intelligence and finance analysis run in parallel and both produce evidence-cited reports with data-quality warnings.",
        "trigger": {"schedule": "weekly"},
        "timeout_seconds": 600,
        "graph": {
            "start": "fanout",
            "nodes": {
                "fanout": {"type": "parallel", "branches": ["bi", "finance"], "next": "gate"},
                "gate": {"type": "approval_gate", "next": "end"},
                "bi": {"type": "agent", "agent": "business_intelligence", "input": {"metrics": "$.input.metrics", "period_days": "$.input.period_days", "question": "$.input.question"}},
                "finance": {"type": "agent", "agent": "finance_analyst", "input": {"months": "$.input.months"}},
                "end": {"type": "end"},
            },
        },
    },
    {
        "key": "order_exception",
        "name": "Order exception → customer update → retention check",
        "description": "Detects delayed/failed orders, drafts customer updates (approval-gated) and hands at-risk customers to the retention agent.",
        "trigger": {"event_types": ["order.updated", "shipment.delayed"]},
        "timeout_seconds": 300,
        "graph": {
            "start": "orders",
            "nodes": {
                "orders": {"type": "agent", "agent": "order_management", "input": {"order_ids": "$.input.order_ids", "scan_all": "$.input.scan_all"}, "next": "gate"},
                "gate": {"type": "approval_gate", "next": "retention"},
                "retention": {"type": "agent", "agent": "customer_retention", "input": {"customer_ids": "$.nodes.orders.data.affected_customer_ids"}, "next": "end"},
                "end": {"type": "end"},
            },
        },
    },
    {
        "key": "release_watch",
        "name": "Deployment → telemetry check → triage",
        "description": "Monitors a release against thresholds and routes anomalies to bug triage and QA planning.",
        "trigger": {"event_types": ["deployment.completed"]},
        "timeout_seconds": 300,
        "graph": {
            "start": "monitor",
            "nodes": {
                "monitor": {"type": "agent", "agent": "release_monitoring", "input": {"service": "$.input.service", "deployment_id": "$.input.deployment_id"}, "next": "anomaly"},
                "anomaly": {"type": "condition", "when": {"path": "$.nodes.monitor.data.anomaly_detected", "equals": True}, "then": "triage", "else": "end"},
                "triage": {"type": "agent", "agent": "bug_triage", "input": {"report": {"title": "$.nodes.monitor.data.incident_title", "description": "$.nodes.monitor.data.summary", "reporter": "release_monitoring"}}, "next": "gate"},
                "gate": {"type": "approval_gate", "next": "end"},
                "end": {"type": "end"},
            },
        },
    },
    {
        "key": "quote_to_po",
        "name": "RFQ quotes → recommendation → approved PO",
        "description": "Compares supplier quotes against policy and requires approval before any purchase order is issued.",
        "trigger": {"event_types": ["rfq.quotes_received"]},
        "timeout_seconds": 300,
        "graph": {
            "start": "compare",
            "nodes": {
                "compare": {"type": "agent", "agent": "procurement", "input": {"rfq_id": "$.input.rfq_id"}, "next": "gate"},
                "gate": {"type": "approval_gate", "next": "end"},
                "end": {"type": "end"},
            },
        },
    },
    {
        "key": "single_agent",
        "name": "Run one agent",
        "description": "Generic wrapper that runs a single agent with the given input (used by the Agent Playground and the /agents/{id}/run endpoint).",
        "trigger": {"manual": True},
        "timeout_seconds": 300,
        "graph": {
            "start": "run",
            "nodes": {
                "run": {"type": "agent", "agent": "$AGENT$", "input": "$.input.payload", "next": "gate"},
                "gate": {"type": "approval_gate", "next": "end"},
                "end": {"type": "end"},
            },
        },
    },
]

EVENT_ROUTING: dict[str, str] = {}
for _wf in BUILTIN_WORKFLOWS:
    for _et in _wf["trigger"].get("event_types", []):
        EVENT_ROUTING[_et] = _wf["key"]
