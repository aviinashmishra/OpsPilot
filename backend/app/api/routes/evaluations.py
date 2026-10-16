"""Agent evaluation runs."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.schemas import EvaluationResultOut, EvaluationRunIn
from app.db.models import EvaluationResult
from app.db.session import get_db
from app.evaluation.harness import run_evaluation

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


def _out(r: EvaluationResult) -> EvaluationResultOut:
    return EvaluationResultOut(id=str(r.id), agent_key=r.agent_key, agent_version=r.agent_version, model=r.model, metrics=r.metrics, case_results=r.case_results, passed=r.passed, created_at=r.created_at)


@router.get("", response_model=list[EvaluationResultOut], summary="Latest evaluation results per agent")
def latest(principal: Principal = Depends(require("agents:read")), db: Session = Depends(get_db)) -> list[EvaluationResultOut]:
    rows = db.execute(select(EvaluationResult).order_by(EvaluationResult.created_at.desc())).scalars().all()
    seen: set[str] = set()
    out = []
    for r in rows:
        if r.agent_key in seen:
            continue
        seen.add(r.agent_key)
        out.append(_out(r))
    return out


@router.post("/run", response_model=EvaluationResultOut, summary="Run the synthetic evaluation dataset for an agent")
def run(body: EvaluationRunIn, principal: Principal = Depends(require("agents:admin")), db: Session = Depends(get_db)) -> EvaluationResultOut:
    result = run_evaluation(db, principal.tenant, body.agent_key)
    return _out(result)


@router.post("/run-all", response_model=list[EvaluationResultOut], summary="Evaluate all agents")
def run_all(principal: Principal = Depends(require("agents:admin")), db: Session = Depends(get_db)) -> list[EvaluationResultOut]:
    from app.agents.registry import agent_registry

    return [_out(run_evaluation(db, principal.tenant, spec.key)) for spec in agent_registry.specs()]
