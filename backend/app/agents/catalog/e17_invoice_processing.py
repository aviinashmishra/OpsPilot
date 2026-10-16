"""Agent 17 - Invoice Processing.

Extracts structured fields from invoice text (model-assisted, regex fallback),
independently re-validates all arithmetic with Decimal math, performs a 3-way
match against purchase orders and goods receipts, detects duplicates, and
stages a payable for human approval. It never releases payment.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import (
    AgentContext,
    AgentInput,
    AgentResult,
    AgentSpec,
    ApprovalRule,
    BaseAgent,
    ProposedAction,
)
from app.agents.common import guard_untrusted, money, parse_dt, to_float
from app.agents.registry import register
from app.agents.services import AgentServices
from app.core.errors import NotFound


class InvoiceIn(AgentInput):
    document_text: str = Field(min_length=10, max_length=100_000)
    document_id: str | None = None
    vendor_hint: str | None = None
    tolerance_pct: float = Field(default=2.0, ge=0, le=10)


class LineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float
    amount: float


class InvoiceFields(BaseModel):
    vendor: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    po_number: str | None = None
    currency: str | None = None
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    lines: list[LineItem] = Field(default_factory=list)


class Discrepancy(BaseModel):
    kind: str
    severity: str
    detail: str
    evidence: list[str]


class InvoiceOut(BaseModel):
    fields: InvoiceFields
    arithmetic_ok: bool
    computed_subtotal: float | None
    computed_total: float | None
    po_match: str  # matched|partial|unmatched|no_po
    receipt_match: str
    duplicate_of: list[str]
    discrepancies: list[Discrepancy]
    missing_fields: list[str]
    recommendation: str
    payment_released: bool = False


_LABEL = {
    "invoice_number": r"\binvoice\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9\-/]+)",
    "po_number": r"\b(?:p\.?o\.?|purchase order)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9\-]+)",
    "invoice_date": r"\b(?:invoice\s*)?date\s*[:\-]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}[/.-][0-9]{1,2}[/.-][0-9]{2,4}|[A-Za-z]{3,9} \d{1,2},? \d{4})",
    "due_date": r"\bdue\s*(?:date)?\s*[:\-]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}[/.-][0-9]{1,2}[/.-][0-9]{2,4}|[A-Za-z]{3,9} \d{1,2},? \d{4})",
    "subtotal": r"\bsub\s*total\s*[:\-]?\s*[$€£]?\s*([\d,]+\.\d{2})",
    "tax": r"\b(?:tax|vat|gst)\s*(?:\(\d+%\))?\s*[:\-]?\s*[$€£]?\s*([\d,]+\.\d{2})",
    "total": r"\b(?:total\s*(?:due|amount)?|amount due|grand total)\s*[:\-]?\s*[$€£]?\s*([\d,]+\.\d{2})",
}
_LINE = re.compile(r"^(.{3,60}?)\s{2,}(\d+(?:\.\d+)?)\s+[$€£]?([\d,]+\.\d{2})\s+[$€£]?([\d,]+\.\d{2})\s*$", re.M)


def heuristic_fields(text: str, vendor_hint: str | None) -> InvoiceFields:
    f: dict[str, Any] = {}
    for key, pat in _LABEL.items():
        hits = re.findall(pat, text, re.I)
        if hits:
            f[key] = hits[-1] if key == "total" else hits[0]
    vendor = vendor_hint
    m = re.search(r"^(?:from|vendor|supplier|bill from)\s*[:\-]?\s*(.+)$", text, re.I | re.M)
    if m:
        vendor = m.group(1).strip()
    elif not vendor:
        vendor = text.strip().splitlines()[0][:80] if text.strip() else None
    cur = "EUR" if "€" in text else "GBP" if "£" in text else "USD"
    lines = [LineItem(description=d.strip(), quantity=float(q), unit_price=to_float(u) or 0, amount=to_float(a) or 0) for d, q, u, a in _LINE.findall(text)]
    return InvoiceFields(vendor=vendor, invoice_number=f.get("invoice_number"), invoice_date=f.get("invoice_date"), due_date=f.get("due_date"), po_number=f.get("po_number"), currency=cur, subtotal=to_float(f.get("subtotal")), tax=to_float(f.get("tax")), total=to_float(f.get("total")), lines=lines)


@register
class InvoiceProcessingAgent(BaseAgent):
    spec = AgentSpec(
        key="invoice_processing",
        name="Invoice Processing Agent",
        department="finance_admin",
        version="1.2.0",
        description="Extracts invoice fields, re-validates arithmetic, performs 3-way PO/receipt matching, detects duplicates and stages payables for approval without ever releasing payment.",
        use_cases=["AP intake", "3-way match", "Duplicate invoice detection"],
        input_model=InvoiceIn,
        output_model=InvoiceOut,
        allowed_tools=["accounting.find_invoices", "accounting.get_purchase_order", "accounting.list_receipts", "accounting.create_payable", "platform.create_task"],
        permission_scopes=["accounting:read", "accounting:write", "tasks:write"],
        policies=["independent_arithmetic_validation", "three_way_match", "never_release_payment", "duplicate_detection"],
        approval_rules=[ApprovalRule(action_type="accounting.create_payable", condition="all payables", required_permission="accounting:write")],
        timeout_seconds=90,
        token_budget=12000,
        risk_level="high",
        baseline_minutes_saved=18,
    )

    def run(self, ctx: AgentContext, payload: InvoiceIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        wrapped = guard_untrusted(result, payload.document_text, "invoice_document")
        fields = services.structured(
            task="invoice_extraction", schema=InvoiceFields,
            system="Extract invoice fields exactly as printed. Do not compute or correct any amounts. Leave fields null when absent. Dates as printed.",
            user=wrapped, heuristic=lambda: heuristic_fields(payload.document_text, payload.vendor_hint),
        )
        src = f"document:{payload.document_id}" if payload.document_id else "input:document_text"
        result.add_evidence(src, excerpt=f"{fields.vendor} #{fields.invoice_number} total {fields.total}", source_type="document")
        # Deterministic sanity: extracted amounts must literally appear in the document.
        for name in ("subtotal", "tax", "total"):
            v = getattr(fields, name)
            if v is not None and f"{v:,.2f}" not in payload.document_text and f"{v:.2f}" not in payload.document_text:
                result.warnings.append(f"Extracted {name} {v:.2f} not found verbatim in document; cleared")
                setattr(fields, name, None)

        missing = [k for k in ("vendor", "invoice_number", "invoice_date", "total") if not getattr(fields, k)]
        disc: list[Discrepancy] = []
        tol = Decimal(str(payload.tolerance_pct)) / 100
        # Arithmetic ---------------------------------------------------------
        computed_sub = computed_total = None
        arithmetic_ok = True
        if fields.lines:
            computed_sub = sum((money(ln.quantity * ln.unit_price) for ln in fields.lines), Decimal("0"))
            for ln in fields.lines:
                if abs(money(ln.quantity * ln.unit_price) - money(ln.amount)) > Decimal("0.01"):
                    arithmetic_ok = False
                    disc.append(Discrepancy(kind="line_arithmetic", severity="high", detail=f"Line '{ln.description}': {ln.quantity} × {ln.unit_price} = {ln.quantity * ln.unit_price:.2f}, invoice shows {ln.amount:.2f}", evidence=[src]))
            if fields.subtotal is not None and abs(computed_sub - money(fields.subtotal)) > Decimal("0.01"):
                arithmetic_ok = False
                disc.append(Discrepancy(kind="subtotal_mismatch", severity="high", detail=f"Lines sum to {computed_sub} but subtotal printed {money(fields.subtotal)}", evidence=[src]))
        if fields.total is not None:
            base = money(fields.subtotal) if fields.subtotal is not None else computed_sub
            if base is not None:
                computed_total = base + money(fields.tax or 0)
                if abs(computed_total - money(fields.total)) > Decimal("0.01"):
                    arithmetic_ok = False
                    disc.append(Discrepancy(kind="total_mismatch", severity="high", detail=f"Subtotal {base} + tax {money(fields.tax or 0)} = {computed_total}, invoice total {money(fields.total)}", evidence=[src]))
        # Duplicates ---------------------------------------------------------
        dup_ids: list[str] = []
        if fields.vendor:
            found = services.tools.call("accounting.find_invoices", vendor=fields.vendor, invoice_number=fields.invoice_number)
            dup_ids += [i["id"] for i in found.get("items", []) if fields.invoice_number]
            if fields.total is not None:
                found2 = services.tools.call("accounting.find_invoices", vendor=fields.vendor, amount=float(money(fields.total)))
                for i in found2.get("items", []):
                    d1, d2 = parse_dt(i.get("invoice_date")), parse_dt(fields.invoice_date)
                    if i["id"] not in dup_ids and d1 and d2 and abs((d1 - d2).days) <= 30:
                        dup_ids.append(i["id"])
                        disc.append(Discrepancy(kind="possible_duplicate", severity="high", detail=f"Same vendor and amount as invoice {i['id']} ({i.get('invoice_number')}) dated {i.get('invoice_date')}", evidence=[f"accounting:invoice:{i['id']}", src]))
        for d in dup_ids:
            result.add_evidence(f"accounting:invoice:{d}", excerpt="existing invoice", source_type="accounting")
            if not any(x.kind == "possible_duplicate" and d in " ".join(x.evidence) for x in disc):
                disc.append(Discrepancy(kind="duplicate_invoice_number", severity="high", detail=f"Invoice number {fields.invoice_number} already recorded as {d}", evidence=[f"accounting:invoice:{d}", src]))
        # 3-way match ----------------------------------------------------------
        po_match, receipt_match = "no_po", "no_po"
        if fields.po_number:
            try:
                po = services.tools.call("accounting.get_purchase_order", po_number=fields.po_number)
                result.add_evidence(f"accounting:po:{fields.po_number}", excerpt=f"total {po.get('total')} vendor {po.get('vendor')}", source_type="accounting")
                po_total = money(po.get("total", 0))
                inv_total = money(fields.total or 0)
                if po.get("vendor") and fields.vendor and po["vendor"].lower() != fields.vendor.lower():
                    disc.append(Discrepancy(kind="vendor_mismatch", severity="high", detail=f"PO vendor '{po['vendor']}' ≠ invoice vendor '{fields.vendor}'", evidence=[f"accounting:po:{fields.po_number}", src]))
                    po_match = "unmatched"
                elif po_total and abs(inv_total - po_total) <= po_total * tol:
                    po_match = "matched"
                elif po_total and inv_total < po_total:
                    po_match = "partial"
                    disc.append(Discrepancy(kind="partial_billing", severity="low", detail=f"Invoice {inv_total} below PO {po_total} (partial delivery?)", evidence=[f"accounting:po:{fields.po_number}"]))
                else:
                    po_match = "unmatched"
                    disc.append(Discrepancy(kind="po_amount_mismatch", severity="high", detail=f"Invoice {inv_total} exceeds PO {po_total} by more than {payload.tolerance_pct}%", evidence=[f"accounting:po:{fields.po_number}", src]))
                receipts = services.tools.call("accounting.list_receipts", po_number=fields.po_number).get("items", [])
                received = sum((money(r.get("amount", 0)) for r in receipts), Decimal("0"))
                for r in receipts:
                    result.add_evidence(f"accounting:receipt:{r['id']}", excerpt=f"received {r.get('amount')}", source_type="accounting")
                if not receipts:
                    receipt_match = "unmatched"
                    disc.append(Discrepancy(kind="no_goods_receipt", severity="medium", detail="No goods receipt recorded for this PO", evidence=[f"accounting:po:{fields.po_number}"]))
                elif received + received * tol >= inv_total:
                    receipt_match = "matched"
                else:
                    receipt_match = "partial"
                    disc.append(Discrepancy(kind="receipt_shortfall", severity="medium", detail=f"Received {received} vs invoiced {inv_total}", evidence=[f"accounting:receipt:{r['id']}" for r in receipts]))
            except NotFound:
                po_match = receipt_match = "unmatched"
                disc.append(Discrepancy(kind="po_not_found", severity="high", detail=f"PO {fields.po_number} not found", evidence=[src]))
        else:
            missing.append("po_number")
        result.missing_information = [f"Invoice field '{m}'" for m in missing]
        high = [d for d in disc if d.severity == "high"]
        if missing and "total" in missing:
            rec = "Cannot stage payable: total missing — request a corrected invoice"
            result.status = "needs_input"
        elif high:
            rec = "Hold for AP review: " + "; ".join(d.kind for d in high)
        elif po_match == "matched" and receipt_match == "matched" and arithmetic_ok:
            rec = "3-way match passed; stage payable for approval"
        else:
            rec = "Stage payable with exceptions noted for reviewer"
        if fields.total is not None:
            payable = {"vendor": fields.vendor, "invoice_number": fields.invoice_number, "invoice_date": fields.invoice_date, "due_date": fields.due_date, "po_number": fields.po_number, "currency": fields.currency, "total": float(money(fields.total)), "match": {"po": po_match, "receipt": receipt_match, "arithmetic_ok": arithmetic_ok}, "discrepancies": [d.model_dump() for d in disc], "source": src}
            result.proposed_actions.append(ProposedAction(action_type="accounting.create_payable", tool_key="accounting.create_payable", payload={"invoice": payable}, reason=rec, risk_level="critical" if high else "high", evidence_refs=result.evidence_refs[:6], estimated_minutes_saved=12))
        if high:
            result.proposed_actions.append(ProposedAction(action_type="platform.create_task", tool_key="platform.create_task", payload={"title": f"AP review: {fields.vendor} invoice {fields.invoice_number or '?'}", "description": "\n".join(f"- [{d.severity}] {d.kind}: {d.detail}" for d in disc), "priority": "high", "labels": ["ap", "exception"], "evidence_refs": result.evidence_refs[:6]}, reason="Discrepancies require human review", risk_level="low", evidence_refs=result.evidence_refs[:3]))
        result.data = InvoiceOut(fields=fields, arithmetic_ok=arithmetic_ok, computed_subtotal=float(computed_sub) if computed_sub is not None else None, computed_total=float(computed_total) if computed_total is not None else None, po_match=po_match, receipt_match=receipt_match, duplicate_of=dup_ids, discrepancies=disc, missing_fields=missing, recommendation=rec, payment_released=False).model_dump()
        result.summary = f"{fields.vendor or 'Unknown vendor'} #{fields.invoice_number or '?'} {fields.currency or ''} {fields.total if fields.total is not None else '?'} — PO {po_match}, receipts {receipt_match}, {len(disc)} discrepancy(ies). {rec}"
        result.confidence = 0.9 if not missing and arithmetic_ok else 0.6
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved
        return result
