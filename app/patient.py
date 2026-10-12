"""Turn a FHIR R4 Bundle (Patient + Conditions + Observations) into a flat PatientProfile."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .vocab import LOINC_SYSTEM, SNOMED_SYSTEM

_ACTIVE_STATUSES = {"active", "recurrence", "relapse"}
_BAD_VERIFICATION = {"entered-in-error", "refuted"}
_BAD_OBS_STATUS = {"entered-in-error", "cancelled"}

@dataclass(frozen=True)
class Condition:
    code: str | None
    system: str | None
    display: str
    active: bool

@dataclass(frozen=True)
class Observation:
    loinc: str
    display: str
    value: float
    unit: str
    on: date

@dataclass(frozen=True)
class PatientProfile:
    id: str
    sex: str | None
    birth_date: date | None
    conditions: tuple[Condition, ...]
    observations: tuple[Observation, ...]

    def age_in_months(self, as_of: date) -> int | None:
        if self.birth_date is None:
            return None
        b = self.birth_date
        months = (as_of.year - b.year) * 12 + (as_of.month - b.month)
        if as_of.day < b.day:
            months -= 1
        return months

    def snomed_codes(self, active_only:bool) -> set[str]:
        return {
            c.code
            for c in self.conditions
            if c.code and c.system == SNOMED_SYSTEM and (c.active or not active_only)
        }
    
    def latest_observation(self, loincs: tuple[str, ...], as_of:date) -> Observation | None:
        """Most recent matching observation on or before `as_of` (ties broken deterministically)."""
        candidates = [
            o 
            for o in self.observations 
            if o.loinc in loincs and o.on <= as_of
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda o: (o.on, o.loinc, o.value))

    def search_terms(self) -> list[str]:
        """Active condition names used to query ClinicalTrials.gov (sorted, de-duplicated)."""
        return sorted({c.display for c in self.conditions if c.active and c.display})

def _parse_date(value: Any) -> date | None:
    """Accept full dates / datetimes; reject partial FHIR dates like '1958' or '1958-03'."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _first_code(codeable: dict[str, Any], preferred_system: str) -> tuple[str | None, str | None, str]:
    codings = codeable.get("coding") or []
    chosen = next((c for c in codings if c.get("system") == preferred_system), codings[0] if codings else {})
    display = codeable.get("text") or chosen.get("display") or ""
    return chosen.get("code"), chosen.get("system"), display


def _coding_code(codeable: dict[str, Any] | None) -> str | None:
    codings = (codeable or {}).get("coding") or []
    return codings[0].get("code") if codings else None


def _parse_condition(r: dict[str, Any]) -> Condition | None:
    if _coding_code(r.get("verificationStatus")) in _BAD_VERIFICATION:
        return None
    code, system, display = _first_code(r.get("code") or {}, SNOMED_SYSTEM)
    status = _coding_code(r.get("clinicalStatus"))
    # FHIR allows clinicalStatus to be absent; we treat that as active.
    active = True if status is None else status in _ACTIVE_STATUSES
    return Condition(code=code, system=system, display=display, active=active)


def _parse_observation(r: dict[str, Any]) -> Observation | None:
    if r.get("status") in _BAD_OBS_STATUS:
        return None
    codings = (r.get("code") or {}).get("coding") or []
    loinc = next((c for c in codings if c.get("system") == LOINC_SYSTEM), None)
    quantity = r.get("valueQuantity") or {}
    when = _parse_date(
        r.get("effectiveDateTime") or r.get("effectiveInstant") or (r.get("effectivePeriod") or {}).get("start")
    )
    value = quantity.get("value")

    if loinc is None or not isinstance(value, (int, float)) or when is None:
        return None

    return Observation(
        loinc=loinc["code"],
        display=loinc.get("display", ""),
        value=float(value),
        unit=quantity.get("unit") or quantity.get("code") or "",
        on=when,
    )


def parse_bundle(bundle: dict[str, Any]) -> PatientProfile:
    if bundle.get("resourceType") != "Bundle":
        raise ValueError("Expected a FHIR Bundle (resourceType 'Bundle').")

    entries = [e for e in bundle.get("entry", []) if isinstance(e.get("resource"), dict)]
    patient_entries = [e for e in entries if e["resource"].get("resourceType") == "Patient"]
    if len(patient_entries) != 1:
        raise ValueError(f"Bundle must contain exactly one Patient, found {len(patient_entries)}.")

    patient = patient_entries[0]["resource"]
    pid = patient.get("id") or "unknown"

    # A resource belongs to this patient if it points at Patient/<id> or the entry's fullUrl
    # (Synthea-style bundles use urn:uuid references).
    refs = {f"Patient/{pid}"}
    if patient_entries[0].get("fullUrl"):
        refs.add(patient_entries[0]["fullUrl"])

    def mine(resource: dict[str, Any]) -> bool:
        ref = (resource.get("subject") or {}).get("reference")
        return ref is None or ref in refs

    conditions: list[Condition] = []
    observations: list[Observation] = []

    for e in entries:
        r = e["resource"]
        if not mine(r):
            continue
        if r.get("resourceType") == "Condition":
            parsed_c = _parse_condition(r)
            if parsed_c:
                conditions.append(parsed_c)

        elif r.get("resourceType") == "Observation":
            parsed_o = _parse_observation(r)
            if parsed_o:
                observations.append(parsed_o)

    gender = patient.get("gender")
    return PatientProfile(
        id=pid,
        sex={"male": "MALE", "female": "FEMALE"}.get(gender),
        birth_date=_parse_date(patient.get("birthDate")),
        conditions=tuple(conditions),
        observations=tuple(observations),
    )

    