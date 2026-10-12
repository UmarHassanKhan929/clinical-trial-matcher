"""ClinicalTrials.gov v2 study JSON  <->  FHIR R4 ResearchStudy  <->  internal Study."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

EXT_BASE = "https://example.org/fhir/StructureDefinition/ctgov-"

# FHIR R4 ResearchStudy.status is coarser than ClinicalTrials.gov's overallStatus, so the
# mapping is lossy (RECRUITING and ENROLLING_BY_INVITATION both become "active").
# We therefore also keep the original value in an extension and gate on THAT.
_FHIR_STATUS = {
    "RECRUITING": "active",
    "ENROLLING_BY_INVITATION": "active",
    "NOT_YET_RECRUITING": "approved",
    "ACTIVE_NOT_RECRUITING": "closed-to-accrual",
    "SUSPENDED": "temporarily-closed-to-accrual",
    "TERMINATED": "administratively-completed",
    "COMPLETED": "completed",
    "WITHDRAWN": "withdrawn",
}

@dataclass(frozen=True)
class Study:
    nct_id: str
    title: str
    ctgov_status: str
    conditions: tuple[str, ...]
    eligibility_text: str
    sex: str  # ALL | MALE | FEMALE
    min_age: str | None
    max_age: str | None

def to_research_study(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one ClinicalTrials.gov v2 study into a FHIR R4 ResearchStudy (or None if unusable)."""
    p = raw.get("protocolSection") or {}
    ident = p.get("identificationModule") or {}
    nct = ident.get("nctId")

    if not nct:
        return None

    overall = (p.get("statusModule") or {}).get("overallStatus", "UNKNOWN")
    elig = p.get("eligibilityModule") or {}
    conditions = (p.get("conditionsModule") or {}).get("conditions") or []

    extensions = [
        {"url": EXT_BASE + "overall-status", "valueString": overall},
        {"url": EXT_BASE + "sex", "valueString": elig.get("sex", "ALL")},
        {"url": EXT_BASE + "eligibility-criteria", "valueString": elig.get("eligibilityCriteria", "")},
    ]

    for key, suffix in (("minimumAge", "minimum-age"), ("maximumAge", "maximum-age")):
        if elig.get(key):
            extensions.append({"url": EXT_BASE + suffix, "valueString": elig[key]})

    return {
        "resourceType": "ResearchStudy",
        "id": nct,
        "identifier": [{"system": "https://clinicaltrials.gov", "value": nct}],
        "title": ident.get("briefTitle") or ident.get("officialTitle") or nct,
        "status": _FHIR_STATUS.get(overall, "in-review"),
        "condition": [{"text": c} for c in conditions],
        "extension": extensions,
    }

def from_research_study(rs: dict[str, Any]) -> Study:
    ext = {e["url"].removeprefix(EXT_BASE): e.get("valueString") for e in rs.get("extension", [])}
    return Study(
        nct_id=rs["id"],
        title=rs.get("title", rs["id"]),
        ctgov_status=ext.get("overall-status") or "UNKNOWN",
        conditions=tuple(c["text"] for c in rs.get("condition", []) if c.get("text")),
        eligibility_text=ext.get("eligibility-criteria") or "",
        sex=ext.get("sex") or "ALL",
        min_age=ext.get("minimum-age"),
        max_age=ext.get("maximum-age"),
    )

