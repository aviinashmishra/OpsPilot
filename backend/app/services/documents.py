"""Safe document handling: text extraction and malicious-content scanning."""

from __future__ import annotations

import re
from typing import Any

from app.llm.safety import scan_for_injection

_SECRET_PATTERNS = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("generic_api_key", re.compile(r"(?i)(api[_-]?key|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{24,}")),
    ("card_number", re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
]


def extract_text(data: bytes, content_type: str) -> str:
    if content_type == "application/pdf":
        # Minimal, dependency-free extraction of literal text runs. For production
        # OCR/layout extraction, plug in a document-AI provider here.
        raw = data.decode("latin-1", errors="ignore")
        runs = re.findall(r"\(([^()]{2,})\)\s*Tj", raw)
        return "\n".join(runs) if runs else ""
    return data.decode("utf-8", errors="replace")


def scan_document(text: str, data: bytes, content_type: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if content_type == "application/pdf":
        raw = data[:2_000_000].decode("latin-1", errors="ignore")
        for marker in ("/JavaScript", "/JS", "/Launch", "/EmbeddedFile", "/OpenAction"):
            if marker in raw:
                findings.append({"kind": "pdf_active_content", "severity": "high", "detail": f"PDF contains {marker}"})
    if b"\x00" in data[:4096] and content_type.startswith("text/"):
        findings.append({"kind": "binary_in_text", "severity": "medium", "detail": "NUL bytes in a text document"})
    inj = scan_for_injection(text)
    for f in inj.findings[:10]:
        findings.append({"kind": f"prompt_injection:{f['kind']}", "severity": "high" if inj.high_risk else "medium", "detail": f["excerpt"]})
    for kind, pat in _SECRET_PATTERNS:
        if kind == "card_number":
            for m in pat.finditer(text or ""):
                digits = re.sub(r"\D", "", m.group(0))
                if 13 <= len(digits) <= 16 and _luhn(digits):
                    findings.append({"kind": "possible_card_number", "severity": "medium", "detail": f"****{digits[-4:]}"})
                    break
        elif pat.search(text or ""):
            findings.append({"kind": f"secret:{kind}", "severity": "high", "detail": "credential-like content detected"})
    return findings


def _luhn(num: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(num)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0
