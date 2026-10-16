"""Deterministic offline planner for the Ops Copilot (used when no LLM key is set).

It maps common operator requests to agent / tool calls with simple, documented
rules, can issue several calls for multi-part requests ("check stock and overdue
tasks"), and writes the answer strictly from the tool results it received. With
LLM_PROVIDER=anthropic, Claude plans instead and this module is not used.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from app.llm.tool_loop import LoopTool, PlannedCall, ToolOutcome

ORDER = re.compile(r"\bORD-\d{3,8}\b", re.I)
RFQ = re.compile(r"\bRFQ-\d+\b", re.I)
RUN_ID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
SERVICE = re.compile(r"\b([a-z]+-api)\b", re.I)

Rule = tuple[str, re.Pattern[str], Callable[[str], PlannedCall | None]]


def _c(name: str, data: dict[str, Any] | None = None) -> Callable[[str], PlannedCall | None]:
    return lambda _t: PlannedCall(name, dict(data or {}))


def _order(text: str) -> PlannedCall | None:
    m = ORDER.search(text)
    if m:
        return PlannedCall("commerce__get_order", {"order_id": m.group(0).upper()})
    return PlannedCall("agent__order_management", {"scan_all": True})


def _shipment(text: str) -> PlannedCall | None:
    m = ORDER.search(text)
    return PlannedCall("commerce__get_shipment", {"order_id": m.group(0).upper()}) if m else None


def _release(text: str) -> PlannedCall | None:
    m = SERVICE.search(text)
    return PlannedCall("agent__release_monitoring", {"service": (m.group(1) if m else "checkout-api").lower()})


def _procure(text: str) -> PlannedCall | None:
    m = RFQ.search(text)
    return PlannedCall("agent__procurement", {"rfq_id": m.group(0).upper() if m else "RFQ-42"})


def _lead(text: str) -> PlannedCall | None:
    m = EMAIL.search(text)
    if m:
        return PlannedCall("crm__find_lead", {"email": m.group(0)})
    return PlannedCall("crm__list_leads", {})


def _run(text: str) -> PlannedCall | None:
    m = RUN_ID.search(text)
    return PlannedCall("ops__get_workflow_run", {"run_id": m.group(0)}) if m else None


def _knowledge(text: str) -> PlannedCall | None:
    return PlannedCall("platform__search_knowledge", {"query": text[:300], "limit": 3})


def _support(text: str) -> PlannedCall | None:
    return PlannedCall("agent__customer_support", {"message": text[:2000]})


RULES: list[Rule] = [
    ("approvals", re.compile(r"\b(approval|approvals|pending|waiting for (review|approval))\b", re.I), _c("ops__list_pending_approvals", {"limit": 10})),
    ("workflow_run", re.compile(r"\b(run|workflow)\b.*[0-9a-f]{8}-", re.I), _run),
    ("order", re.compile(r"\b(order|orders|shipment|tracking|delayed|late deliver)|\bORD-\d{3,8}\b", re.I), _order),
    ("shipment", re.compile(r"\bORD-\d+.*\b(track|ship|where)|\b(track|ship|where)\b.*ORD-\d+", re.I), _shipment),
    ("inventory", re.compile(r"\b(inventory|stock|reorder|replenish|forecast)\b", re.I), _c("agent__inventory_forecasting", {"horizon_days": 30})),
    ("kpi", re.compile(r"\b(kpi|kpis|metrics|weekly report|business report|dashboard numbers)\b", re.I), _c("agent__business_intelligence", {"period_days": 14})),
    ("tasks", re.compile(r"\b(overdue|blocked|tasks?|deadline)\b", re.I), _c("agent__workflow_coordinator", {"scope": "overdue"})),
    ("retention", re.compile(r"\b(churn|at[- ]risk|retention|inactive customers?)\b", re.I), _c("agent__customer_retention", {"inactivity_days": 60})),
    ("release", re.compile(r"\b(release|deploy|deployment|error rate|latency|incident)\b", re.I), _release),
    ("procurement", re.compile(r"\b(rfq|quotes?|supplier|purchase order|procure)\b", re.I), _procure),
    ("expenses", re.compile(r"\b(expense|expenses|reimburse)\b", re.I), _c("agent__expense_audit", {"status": "submitted"})),
    ("receivables", re.compile(r"\b(overdue invoices?|payment reminder|dunning|unpaid|receivable)\b", re.I), _c("agent__payment_followup", {})),
    ("feedback", re.compile(r"\b(feedback|reviews|themes|feature requests?|voice of (the )?customer)\b", re.I), _c("agent__product_research", {"since_days": 90, "min_theme_size": 2})),
    ("finance", re.compile(r"\b(cost|costs|budget|roi|spend|savings)\b", re.I), _c("agent__finance_analyst", {"months": 3})),
    ("sop", re.compile(r"\b(sop|compliance|audit (the )?process|onboarding process)\b", re.I), _c("agent__sop_compliance", {"process": "customer_onboarding"})),
    ("leads", re.compile(r"\b(leads?|prospects?|pipeline)\b", re.I), _lead),
    ("bugs", re.compile(r"\b(bugs?|issues? in (jira|the tracker)|open issues)\b", re.I), _c("issues__search", {"query": "", "limit": 10})),
    ("customer_q", re.compile(r"\b(customer (asks|asked|wants to know)|answer (this|the) customer)\b", re.I), _support),
    ("policy", re.compile(r"\b(policy|shipping|returns?|warranty|refund|how (do|does|long))\b", re.I), _knowledge),
    ("agents", re.compile(r"\b(what can you do|which agents|list (the )?agents|help)\b", re.I), _c("ops__list_agents")),
]


class OfflinePlanner:
    def plan(self, user_text: str, done: list[tuple[PlannedCall, ToolOutcome]], iteration: int, tools: dict[str, LoopTool]) -> list[PlannedCall]:
        if iteration > 1:
            # Follow-up step: after an order lookup, also fetch its shipment (a simple 2-step plan).
            follow: list[PlannedCall] = []
            for call, outcome in done:
                if call.name == "commerce__get_order" and not outcome.is_error and not any(c.name == "commerce__get_shipment" for c, _ in done):
                    follow.append(PlannedCall("commerce__get_shipment", {"order_id": call.input["order_id"]}))
            return [c for c in follow if c.name in tools]
        calls: list[PlannedCall] = []
        seen: set[str] = set()
        for _rule, pattern, build in RULES:
            if pattern.search(user_text):
                call = build(user_text)
                if call and call.name in tools and call.name not in seen:
                    calls.append(call)
                    seen.add(call.name)
            if len(calls) >= 4:
                break
        if not calls:
            fallback = _knowledge(user_text)
            if fallback and fallback.name in tools:
                calls.append(fallback)
            if "ops__list_agents" in tools:
                calls.append(PlannedCall("ops__list_agents", {}))
        return calls

    def answer(self, user_text: str, done: list[tuple[PlannedCall, ToolOutcome]]) -> str:
        if not done:
            return "I couldn't find a tool or agent for that request. Try asking about orders, inventory, overdue tasks, KPIs, approvals, leads, releases, expenses, invoices, suppliers or customer feedback."
        lines = ["Here's what I found (offline planner: answers come straight from the tools below; configure an LLM provider in .env for AI planning and reasoning):", ""]
        approvals: list[str] = []
        for call, outcome in done:
            label = call.name.replace("agent__", "").replace("__", ".").replace("_", " ")
            if outcome.is_error:
                lines.append(f"- {label}: could not complete ({outcome.summary})")
                continue
            lines.append(f"- {label}: {outcome.summary or 'done'}")
            detail = _detail(call, outcome)
            if detail:
                lines.append(f"  {detail}")
            approvals.extend(outcome.approval_ids)
        if approvals:
            lines += ["", f"{len(approvals)} proposed action(s) are waiting for human approval in the Approval Center. I can't approve them."]
        return "\n".join(lines)


def _detail(call: PlannedCall, outcome: ToolOutcome) -> str:
    c = outcome.content if isinstance(outcome.content, dict) else {}
    data = c.get("data") if isinstance(c.get("data"), dict) else c
    if call.name == "ops__list_pending_approvals":
        items = c.get("pending", [])
        return "; ".join(f"{i['action_type']} ({i['risk']})" for i in items[:5]) if items else "nothing is waiting"
    if call.name == "commerce__get_order":
        return f"status {c.get('status')}, total {c.get('total')} {c.get('currency', '')}".strip()
    if call.name == "commerce__get_shipment":
        return f"{c.get('carrier')} {c.get('tracking_number')} - {c.get('status')}, expected {c.get('expected_delivery')}" if c.get("found") else "no shipment recorded yet"
    if call.name == "platform__search_knowledge":
        items = c.get("items", [])
        return f"\"{items[0]['text'][:220]}\" ({items[0]['document_name']})" if items else "no matching documents"
    if call.name == "ops__list_agents":
        return ", ".join(a["name"].replace(" Agent", "") for a in c.get("agents", [])[:25])
    if call.name == "agent__customer_support" and isinstance(data, dict):
        return str(data.get("answer", ""))[:300]
    if call.name == "agent__business_intelligence" and isinstance(data, dict):
        return str(data.get("narrative", ""))[:300]
    if isinstance(data, dict):
        for key in ("recommendation", "summary", "narrative"):
            if data.get(key):
                return str(data[key])[:300]
    return ""
