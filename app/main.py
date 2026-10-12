"""FastAPI service: /match (FR-1..5) and /candidates (FR-6), plus the htmx UI at /."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .ingestion import TrialRepository
from .schemas import MatchRequest, MatchResponse, RegistrationRequest
from .service import get_repository, register_subject, run_match
from .ui import router as ui_router


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

app.include_router(ui_router)
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")


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
        return await run_match(req.bundle, req.as_of or date.today(), include_ineligible, repo)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"ClinicalTrials.gov request failed: {exc}") from exc


@app.post("/candidates", status_code=201)
def register_candidate(req: RegistrationRequest, request: Request, response: Response) -> dict[str, Any]:
    """Idempotent: 201 the first time, 200 with the identical resource on every repeat."""
    subject, status = register_subject(req.patient_id, req.nct_id, request.app.state.subjects)
    response.status_code = status
    return subject
