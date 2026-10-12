"""FastAPI service: /match (FR-1..5) and /candidates (FR-6)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response

from . import __version__
from .fhir_study import from_research_study
from .ingestion import TrialRepository
from .matcher import evaluate
from .patient import parse_bundle
from .schemas import MatchRequest, MatchResponse, RegistrationRequest, Verdict

_VERDICT_RANK = {Verdict.ELIGIBLE: 0, Verdict.POTENTIAL: 1, Verdict.INELIGIBLE: 2}
# Fixed namespace => the same (patient, trial) pair always yields the same ResearchSubject id.
_SUBJECT_NAMESPACE = uuid.UUID("6f1e1b7e-0f0e-4d57-9a53-3a6b0f3c2d11")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": f"clinical-trial-matcher/{__version__}"}) as http:
        app.state.repo = TrialRepository(http)
        yield


app = FastAPI(
    title="Clinical Trial Matcher",
    version=__version__,
    description="Deterministic, explainable clinical trial prescreening over FHIR R4.",
    lifespan=lifespan,
)
app.state.subjects = {}  # in-memory ResearchSubject store (swap for a FHIR server / DB in production)


def get_repository(request: Request) -> TrialRepository:
    return request.app.state.repo


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/match", response_model=MatchResponse)
async def match(
    req: MatchRequest,
    include_ineligible: bool = Query(False, alias="includeIneligible"),
    repo: TrialRepository = Depends(get_repository),
) -> MatchResponse:
    try:
        patient = parse_bundle(req.bundle)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    terms = patient.search_terms()
    if not terms:
        raise HTTPException(status_code=422, detail="Patient has no active conditions to search trials for.")

    as_of = req.as_of or date.today()
    studies: dict[str, dict[str, Any]] = {}
    try:
        for term in terms:
            for resource in await repo.recruiting_for(term):
                studies[resource["id"]] = resource
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"ClinicalTrials.gov request failed: {exc}") from exc

    results = [evaluate(from_research_study(rs), patient, as_of) for rs in studies.values()]
    if not include_ineligible:
        results = [r for r in results if r.verdict is not Verdict.INELIGIBLE]
    results.sort(key=lambda r: (_VERDICT_RANK[r.verdict], -r.score, r.nct_id))
    return MatchResponse(patient_id=patient.id, as_of=as_of, results=results)


@app.post("/candidates", status_code=201)
def register_candidate(req: RegistrationRequest, request: Request, response: Response) -> dict[str, Any]:
    """Idempotent: 201 the first time, 200 with the identical resource on every repeat."""
    subject_id = str(uuid.uuid5(_SUBJECT_NAMESPACE, f"{req.patient_id}|{req.nct_id}"))
    store: dict[str, dict[str, Any]] = request.app.state.subjects
    if subject_id in store:
        response.status_code = 200
        return store[subject_id]
    subject = {
        "resourceType": "ResearchSubject",
        "id": subject_id,
        "status": "candidate",
        "study": {"reference": f"ResearchStudy/{req.nct_id}"},
        "individual": {"reference": f"Patient/{req.patient_id}"},
    }
    store[subject_id] = subject
    return subject
