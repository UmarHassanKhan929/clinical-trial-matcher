"""Engine calls shared by the JSON API (main.py) and the htmx UI (ui.py)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import Request

from .fhir_study import from_research_study
from .ingestion import TrialRepository
from .matcher import evaluate
from .patient import parse_bundle
from .schemas import MatchResponse, Verdict

_VERDICT_RANK = {Verdict.ELIGIBLE: 0, Verdict.POTENTIAL: 1, Verdict.INELIGIBLE: 2}
# Fixed namespace => the same (patient, trial) pair always yields the same ResearchSubject id.
_SUBJECT_NAMESPACE = uuid.UUID("6f1e1b7e-0f0e-4d57-9a53-3a6b0f3c2d11")


def get_repository(request: Request) -> TrialRepository:
    return request.app.state.repo


async def run_match(
    bundle: dict[str, Any],
    as_of: date,
    include_ineligible: bool,
    repo: TrialRepository,
) -> MatchResponse:
    """One match run: parse the bundle, fetch recruiting trials, evaluate, sort.

    Raises ValueError on bad input (bundle or no searchable conditions) and
    httpx.HTTPError when ClinicalTrials.gov fails; callers map those to their
    own transport (HTTP status codes / UI error fragments).
    """
    patient = parse_bundle(bundle)
    terms = patient.search_terms()
    if not terms:
        raise ValueError("Patient has no active conditions to search trials for.")

    studies: dict[str, dict[str, Any]] = {}
    for term in terms:
        for resource in await repo.recruiting_for(term):
            studies[resource["id"]] = resource

    results = [evaluate(from_research_study(rs), patient, as_of) for rs in studies.values()]
    if not include_ineligible:
        results = [r for r in results if r.verdict is not Verdict.INELIGIBLE]
    results.sort(key=lambda r: (_VERDICT_RANK[r.verdict], -r.score, r.nct_id))
    return MatchResponse(patient_id=patient.id, as_of=as_of, results=results)


def register_subject(
    patient_id: str,
    nct_id: str,
    store: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    """Idempotent registration: (subject, 201) the first time, (subject, 200) after."""
    subject_id = str(uuid.uuid5(_SUBJECT_NAMESPACE, f"{patient_id}|{nct_id}"))
    if subject_id in store:
        return store[subject_id], 200
    subject = {
        "resourceType": "ResearchSubject",
        "id": subject_id,
        "status": "candidate",
        "study": {"reference": f"ResearchStudy/{nct_id}"},
        "individual": {"reference": f"Patient/{patient_id}"},
    }
    store[subject_id] = subject
    return subject, 201
