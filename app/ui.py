"""htmx UI: server-rendered fragments over the same engine as the JSON API."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from .ingestion import TrialRepository
from .schemas import RegistrationRequest
from .service import get_repository, register_subject, run_match

router = APIRouter()

_APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_APP_DIR / "templates"))
SAMPLE_BUNDLE = _APP_DIR.parent / "samples" / "patient_bundle.json"


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"bundle_text": ""})


@router.get("/sample-bundle", response_class=HTMLResponse)
def sample_bundle(request: Request) -> HTMLResponse:
    pretty = json.dumps(json.loads(SAMPLE_BUNDLE.read_text()), indent=2)
    return templates.TemplateResponse(request, "bundle_field.html", {"bundle_text": pretty})


@router.post("/match-ui", response_class=HTMLResponse)
async def match_ui(
    request: Request,
    repo: TrialRepository = Depends(get_repository),
    bundle_text: str = Form("", alias="bundleText"),
    bundle_file: UploadFile | None = File(None, alias="bundleFile"),
    as_of: str = Form("", alias="asOf"),
    include_ineligible: bool = Form(False, alias="includeIneligible"),
) -> HTMLResponse:
    try:
        raw = bundle_text
        if bundle_file is not None and bundle_file.filename:
            raw = (await bundle_file.read()).decode("utf-8", errors="replace")
        if not raw.strip():
            raise ValueError("Paste a FHIR Bundle JSON or upload a .json file.")
        try:
            bundle = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Bundle is not valid JSON: {exc}") from exc
        if not isinstance(bundle, dict):
            raise ValueError("Bundle must be a JSON object.")

        when = date.fromisoformat(as_of) if as_of else date.today()
        resp = await run_match(bundle, when, include_ineligible, repo)
    except ValueError as exc:
        return templates.TemplateResponse(request, "error.html", {"message": str(exc)})
    except httpx.HTTPError:
        return templates.TemplateResponse(
            request, "error.html", {"message": "ClinicalTrials.gov request failed — try again shortly."}
        )
    return templates.TemplateResponse(request, "results.html", {"resp": resp})


@router.post("/candidates-ui", response_class=HTMLResponse)
def candidates_ui(
    request: Request,
    patient_id: str = Form(alias="patientId"),
    nct_id: str = Form(alias="nctId"),
) -> HTMLResponse:
    try:
        req = RegistrationRequest(patient_id=patient_id, nct_id=nct_id)
    except ValidationError:
        return templates.TemplateResponse(
            request, "error.html", {"message": "Registration needs a patient id and an NCT id (NCT + 8 digits)."}
        )
    subject, status = register_subject(req.patient_id, req.nct_id, request.app.state.subjects)
    return templates.TemplateResponse(request, "registered.html", {"subject": subject, "status": status})
