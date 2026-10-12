"""Orchestrates the two-stage engine for one (study, patient) pair."""

from __future__ import annotations

from datetime import date

from .fhir_study import Study
from .patient import PatientProfile
from .schemas import MatchResult, Verdict
from .scoring import roll_up
from .stage1 import run_gates
from .stage2 import evaluate_criteria


def evaluate(study: Study, patient: PatientProfile, as_of: date) -> MatchResult:
    gates = run_gates(study, patient, as_of)
    if not all(g.passed for g in gates):
        # Stage 1 failure short-circuits: Stage 2 (the slower text analysis) never runs.
        return MatchResult(
            nct_id=study.nct_id,
            title=study.title,
            verdict=Verdict.INELIGIBLE,
            score=0.0,
            hard_gates_passed=False,
            gates=gates,
            criteria=[],
        )
    criteria = evaluate_criteria(study.eligibility_text, patient, as_of)
    verdict, score = roll_up(criteria)
    return MatchResult(
        nct_id=study.nct_id,
        title=study.title,
        verdict=verdict,
        score=score,
        hard_gates_passed=True,
        gates=gates,
        criteria=criteria,
    )
