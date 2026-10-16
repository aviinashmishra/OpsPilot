from datetime import UTC, datetime

from app.agents.catalog.a01_lead_qualification import normalize_lead
from app.agents.common import (
    money,
    number_lines,
    resolve_deadline,
    strip_protected,
    to_float,
    wilson_interval,
)
from app.services.retrieval import chunk_text, tokenize

BASE = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)  # a Wednesday


def test_resolve_deadline_rules():
    assert resolve_deadline("by Friday", BASE)[0].date().isoformat() == "2026-10-16"
    assert resolve_deadline("tomorrow", BASE)[0].date().isoformat() == "2026-10-15"
    assert resolve_deadline("end of week", BASE)[0].date().isoformat() == "2026-10-16"
    assert resolve_deadline("by Wednesday", BASE)[0].date().isoformat() == "2026-10-21"
    assert resolve_deadline("in 2 weeks", BASE)[0].date().isoformat() == "2026-10-28"
    assert resolve_deadline("by November 12", BASE)[0].date().isoformat() == "2026-11-12"
    assert resolve_deadline("soon", BASE) == (None, "ambiguous")
    assert resolve_deadline(None, BASE) == (None, "none")


def test_to_float_and_money():
    assert to_float("$12,500.50") == 12500.5
    assert to_float("20k") == 20000
    assert to_float("n/a") is None
    assert str(money(10.005)) == "10.01"


def test_strip_protected():
    clean, removed = strip_protected({"name": "a", "Age": 3, "gender": "x", "email": "e"})
    assert set(removed) == {"Age", "gender"} and "name" in clean and "Age" not in clean


def test_normalize_lead():
    lead = normalize_lead({"Name": "ana SILVA", "Email": "Ana@X.TEST", "Phone": "+1 (555) 010-0123", "employees": "250", "Industry": "Retail"})
    assert lead["name"] == "Ana Silva" and lead["email"] == "ana@x.test" and lead["phone"] == "+15550100123"
    assert lead["company_size"] == 250 and lead["industry"] == "retail"


def test_number_lines_with_speakers_and_timestamps():
    lines = number_lines("[00:01] Sarah: hi\n\nPriya: we need SSO\nno speaker line")
    assert lines[0]["speaker"] == "Sarah" and lines[0]["timestamp"] == "00:01"
    assert lines[1]["line"] == 3 and lines[2]["speaker"] is None


def test_wilson_interval_bounds():
    lo, hi = wilson_interval(5, 10)
    assert 0 <= lo < 0.5 < hi <= 1
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_chunking_and_tokenize():
    chunks = chunk_text("# Shipping\nStandard shipping takes 3-5 days.\n\n# Returns\nReturn within 30 days.")
    assert len(chunks) == 2 and chunks[0][0] == "Shipping"
    assert "shipping" in tokenize("The shipping policy")
