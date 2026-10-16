"""Deterministic helpers shared by agents (no I/O, no model calls)."""

from __future__ import annotations

import hashlib
import math
import re
import statistics
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from dateutil import parser as dateparser
from dateutil.relativedelta import FR, MO, SA, SU, TH, TU, WE, relativedelta

from app.agents.base import AgentResult
from app.llm.safety import scan_for_injection, wrap_untrusted

PROTECTED_ATTRIBUTES = {
    "age", "date_of_birth", "dob", "birthdate", "gender", "sex", "race", "ethnicity", "religion", "nationality", "national_origin",
    "marital_status", "disability", "pregnancy", "sexual_orientation", "veteran_status", "genetic_information", "political_affiliation",
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "for", "on", "with", "by", "at", "be", "as", "it", "this", "that", "are",
    "we", "you", "i", "do", "does", "can", "how", "what", "my", "our", "your", "was", "were", "has", "have", "had", "not", "no",
    "but", "so", "if", "they", "them", "their", "its", "from", "will", "would", "could", "should", "just", "very", "really", "too",
    "also", "about", "there", "here", "when", "which", "who", "been", "me", "us", "all", "any", "more", "some", "than", "then", "into",
    "after", "before", "out", "up", "get", "got", "one", "app", "product", "please", "thanks", "thank", "hi", "hello", "im", "dont",
}


def stable_id(prefix: str, *parts: Any, length: int = 6) -> str:
    h = hashlib.sha256("|".join(str(p).lower().strip() for p in parts).encode()).hexdigest()[:length].upper()
    return f"{prefix}-{h}"


def money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    if isinstance(value, int | float):
        return float(value)
    m = re.search(r"-?\d[\d,]*\.?\d*", str(value))
    if not m:
        return default
    try:
        num = float(m.group(0).replace(",", ""))
    except ValueError:
        return default
    s = str(value).lower()
    if re.search(r"\d\s*k\b", s):
        num *= 1000
    elif re.search(r"\d\s*(m|mm|million)\b", s):
        num *= 1_000_000
    return num


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = dateparser.parse(str(value))
        except (ValueError, OverflowError):
            return None
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def days_between(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 86400


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in STOPWORDS and len(t) > 2]


def number_lines(text: str) -> list[dict[str, Any]]:
    """Split a transcript into numbered lines with optional speaker labels."""
    out = []
    for i, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*(.*)$", line)
        ts = None
        if m:
            ts, line = m.group(1), m.group(2)
        sm = re.match(r"^([A-Z][\w .'-]{0,40}?):\s+(.*)$", line)
        speaker, content = (sm.group(1).strip(), sm.group(2).strip()) if sm else (None, line)
        out.append({"line": i, "speaker": speaker, "text": content, "timestamp": ts})
    return out


def guard_untrusted(result: AgentResult, text: str, label: str, max_chars: int = 40_000) -> str:
    """Scan untrusted text, record warnings, and return a delimited version for prompts."""
    scan = scan_for_injection(text or "")
    if scan.detected:
        result.warnings.extend(scan.warning_messages()[:5])
        result.data.setdefault("_security", {})["prompt_injection_detected"] = True
    return wrap_untrusted(text or "", label, max_chars)


def strip_protected(record: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    removed = [k for k in record if k.lower() in PROTECTED_ATTRIBUTES]
    return {k: v for k, v in record.items() if k.lower() not in PROTECTED_ATTRIBUTES}, removed


_WEEKDAYS = {"monday": MO, "tuesday": TU, "wednesday": WE, "thursday": TH, "friday": FR, "saturday": SA, "sunday": SU}
_AMBIGUOUS_DEADLINES = {"soon", "asap", "later", "sometime", "eventually", "at some point", "when possible", "shortly"}


def resolve_deadline(phrase: str | None, base: datetime) -> tuple[datetime | None, str]:
    """Deterministically resolve a relative deadline phrase. Returns (datetime|None, status)
    where status is 'resolved' | 'ambiguous' | 'none'."""
    if not phrase:
        return None, "none"
    p = phrase.lower().strip().rstrip(".")
    if any(a in p for a in _AMBIGUOUS_DEADLINES):
        return None, "ambiguous"
    eod = base.replace(hour=17, minute=0, second=0, microsecond=0)
    if p in {"today", "eod", "end of day", "by end of day", "by eod"}:
        return eod, "resolved"
    if "tomorrow" in p:
        return eod + timedelta(days=1), "resolved"
    if "end of week" in p or p in {"eow", "by eow", "this week"}:
        return eod + relativedelta(weekday=FR(+1)), "resolved"
    if "next week" in p:
        return eod + relativedelta(weeks=+1, weekday=FR(+1)), "resolved"
    if "end of month" in p or "eom" in p:
        return (eod + relativedelta(day=31)), "resolved"
    m = re.search(r"in (\d+) (day|days|week|weeks)", p)
    if m:
        n = int(m.group(1))
        return eod + (timedelta(days=n) if m.group(2).startswith("day") else timedelta(weeks=n)), "resolved"
    for name, wd in _WEEKDAYS.items():
        if name in p:
            # Rule: "<weekday>" and "next <weekday>" both mean the first occurrence strictly after the meeting date.
            target = (eod + timedelta(days=1)) + relativedelta(weekday=wd(+1))
            return target, "resolved"
    if re.search(r"\d", p) or any(mon in p for mon in ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")):
        try:
            cleaned = re.sub(r"^(by|before|on|due)\s+", "", p)
            dt = dateparser.parse(cleaned, default=base.replace(hour=17, minute=0, second=0, microsecond=0, tzinfo=None))
            if dt is not None:
                dt = dt.replace(tzinfo=UTC)
                if dt < base - timedelta(days=1) and not re.search(r"\d{4}", p):
                    dt = dt.replace(year=dt.year + 1)
                return dt, "resolved"
        except (ValueError, OverflowError):
            return None, "ambiguous"
    return None, "ambiguous"


def linear_slope(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(values) / n
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, values, strict=True)) / den if den else 0.0


def pearson(a: list[float], b: list[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 5:
        return None
    a, b = a[-n:], b[-n:]
    try:
        return statistics.correlation(a, b)
    except statistics.StatisticsError:
        return None


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def z_for_service_level(level: float) -> float:
    table = {0.8: 0.8416, 0.85: 1.0364, 0.9: 1.2816, 0.95: 1.6449, 0.975: 1.96, 0.98: 2.0537, 0.99: 2.3263}
    closest = min(table, key=lambda k: abs(k - level))
    return table[closest]


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def contains_any(text: str, words: list[str] | set[str]) -> list[str]:
    t = (text or "").lower()
    return [w for w in words if re.search(r"\b" + re.escape(w) + r"\b", t)]
