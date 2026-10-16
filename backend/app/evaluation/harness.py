"""Synthetic evaluation harness.

Each agent ships an evaluation dataset (app/evaluation/datasets.py). A case is
{input, expect} where `expect` lists deterministic checks:
  status: expected result status
  data.<path>: expected value (== comparison, or {"gte": x}, {"contains": y}, {"len_gte": n})
  actions_include: tool keys that must appear among proposed actions
  actions_exclude: tool keys that must NOT appear
  evidence_min: minimum number of evidence refs
  extract: {"field": path, "expected": [...]} -> precision/recall for list fields
Results are stored in evaluation_results with aggregate metrics.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.runner import run_agent
from app.core.errors import OpsPilotError
from app.db.models import EvaluationDataset, EvaluationResult, Tenant
from app.evaluation.datasets import DATASETS


def _get(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        else:
            return None
    return cur


def _check(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict) and set(expected) & {"gte", "lte", "contains", "len_gte", "len", "in", "ne"}:
        if "gte" in expected and not (isinstance(actual, int | float) and actual >= expected["gte"]):
            return False
        if "lte" in expected and not (isinstance(actual, int | float) and actual <= expected["lte"]):
            return False
        if "contains" in expected and not (actual is not None and expected["contains"] in actual):
            return False
        if "len_gte" in expected and not (hasattr(actual, "__len__") and len(actual) >= expected["len_gte"]):
            return False
        if "len" in expected and not (hasattr(actual, "__len__") and len(actual) == expected["len"]):
            return False
        if "in" in expected and actual not in expected["in"]:
            return False
        if "ne" in expected and actual == expected["ne"]:
            return False
        return True
    return actual == expected


def _prf(predicted: list[Any], expected: list[Any]) -> dict[str, float]:
    p, e = {str(x).lower() for x in predicted}, {str(x).lower() for x in expected}
    tp = len(p & e)
    precision = tp / len(p) if p else (1.0 if not e else 0.0)
    recall = tp / len(e) if e else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def ensure_datasets(db: Session) -> int:
    n = 0
    for key, ds in DATASETS.items():
        row = db.execute(select(EvaluationDataset).where(EvaluationDataset.agent_key == key, EvaluationDataset.name == ds["name"], EvaluationDataset.version == ds.get("version", 1))).scalar_one_or_none()
        if row is None:
            db.add(EvaluationDataset(agent_key=key, name=ds["name"], version=ds.get("version", 1), description=ds.get("description"), cases=ds["cases"]))
            n += 1
        else:
            row.cases = ds["cases"]
    db.flush()
    return n


def run_evaluation(db: Session, tenant: Tenant, agent_key: str, dataset_name: str | None = None) -> EvaluationResult:
    ensure_datasets(db)
    db.commit()
    stmt = select(EvaluationDataset).where(EvaluationDataset.agent_key == agent_key)
    if dataset_name:
        stmt = stmt.where(EvaluationDataset.name == dataset_name)
    ds = db.execute(stmt.order_by(EvaluationDataset.version.desc())).scalars().first()
    if ds is None:
        raise OpsPilotError(f"No evaluation dataset for agent '{agent_key}'", code="not_found")
    case_results: list[dict[str, Any]] = []
    extraction: list[dict[str, float]] = []
    passed = 0
    latencies: list[int] = []
    cost = 0.0
    unsupported = 0
    interventions = 0
    models: set[str] = set()
    for case in ds.cases:
        started = time.perf_counter()
        checks: list[dict[str, Any]] = []
        ok = True
        try:
            out = run_agent(db, tenant=tenant, agent_key=agent_key, input=case["input"], actor_id="evaluation", permissions=["*"], correlation_id=f"eval-{agent_key}", execute_actions=False)
            res = out.result
            latencies.append(out.latency_ms)
            cost += float(out.usage.get("cost_usd", 0))
            models.update(out.usage.get("models", []))
            if res.status in {"needs_approval", "needs_input", "escalated"}:
                interventions += 1
            unsupported += sum(1 for w in res.warnings if "unsupported" in w.lower() or "not found in" in w.lower() or "discarded" in w.lower())
            exp = case.get("expect", {})
            for key, expected in exp.items():
                if key == "status":
                    got = res.status
                    c = _check(got, expected)
                elif key == "actions_include":
                    tools = {a.tool_key for a in res.proposed_actions}
                    got = sorted(tools)
                    c = all(t in tools for t in expected)
                elif key == "actions_exclude":
                    tools = {a.tool_key for a in res.proposed_actions}
                    got = sorted(tools)
                    c = not any(t in tools for t in expected)
                elif key == "evidence_min":
                    got = len(res.evidence_refs)
                    c = got >= expected
                elif key == "warnings_contain":
                    got = res.warnings
                    c = any(expected.lower() in w.lower() for w in res.warnings)
                elif key == "missing_min":
                    got = len(res.missing_information)
                    c = got >= expected
                elif key == "extract":
                    got = _get(res.data, expected["field"]) or []
                    if expected.get("item_field"):
                        got = [_get(g, expected["item_field"]) for g in got if isinstance(g, dict)]
                    m = _prf(got, expected["expected"])
                    extraction.append(m)
                    c = m["f1"] >= expected.get("min_f1", 0.6)
                    got = m
                elif key.startswith("data."):
                    got = _get(res.data, key[5:])
                    c = _check(got, expected)
                else:
                    got, c = None, True
                checks.append({"check": key, "expected": expected, "actual": got, "passed": c})
                ok = ok and c
        except Exception as exc:  # noqa: BLE001
            checks.append({"check": "exception", "expected": "no exception", "actual": f"{type(exc).__name__}: {str(exc)[:200]}", "passed": False})
            ok = False
            latencies.append(int((time.perf_counter() - started) * 1000))
        passed += 1 if ok else 0
        case_results.append({"name": case.get("name", "case"), "passed": ok, "checks": checks})
    n = len(ds.cases)
    lat = sorted(latencies)
    metrics = {
        "cases": n,
        "passed": passed,
        "accuracy": round(passed / n, 4) if n else 0.0,
        "extraction_precision": round(sum(e["precision"] for e in extraction) / len(extraction), 4) if extraction else None,
        "extraction_recall": round(sum(e["recall"] for e in extraction) / len(extraction), 4) if extraction else None,
        "unsupported_claim_rate": round(unsupported / n, 4) if n else 0.0,
        "human_intervention_rate": round(interventions / n, 4) if n else 0.0,
        "cost_per_case_usd": round(cost / n, 6) if n else 0.0,
        "p50_latency_ms": lat[len(lat) // 2] if lat else None,
        "p95_latency_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
    }
    from app.agents.registry import agent_registry

    row = EvaluationResult(dataset_id=ds.id, tenant_id=tenant.id, agent_key=agent_key, agent_version=agent_registry.get(agent_key).spec.version, model=",".join(sorted(models)) or None, metrics=metrics, case_results=case_results, passed=passed == n)
    db.add(row)
    db.commit()
    return row
