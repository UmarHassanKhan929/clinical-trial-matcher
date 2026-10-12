"""FR-3 Stage 1: fast Boolean hard gates. Pure functions, no I/O, no regex-heavy work."""

from __future__ import annotations

import re
from datetime import date

from .fhir_study import Study
from .patient import PatientProfile
from .schemas import GateResult
from .vocab import find_diseases, normalize

_MONTHS_PER_UNIT = {"year": 12.0, "month": 1.0, "week": 7 / 30.4375, "day": 1 / 30.4375}
_AGE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(year|month|week|day)s?\s*$", re.I)


def parse_age_to_months(value: str | None) -> float | None:
    """'18 Years' -> 216.0, '6 Months' -> 6.0, 'N/A' / None -> None (no bound)."""
    if value is None or value.strip().upper() in {"", "N/A", "NA"}:
        return None
    m = _AGE_RE.match(value)
    if not m:
        raise ValueError(f"Unparsable age bound: {value!r}")
    return float(m.group(1)) * _MONTHS_PER_UNIT[m.group(2).lower()]


def _format_age(months: int) -> str:
    return f"{months} months" if months < 24 else f"{months // 12} years"


def _status_gate(study: Study) -> GateResult:
    ok = study.ctgov_status == "RECRUITING"
    return GateResult(
        name="recruitmentStatus",
        passed=ok,
        evidence=f"Study status is {study.ctgov_status}" + ("." if ok else "; only RECRUITING studies are matched."),
    )


def _sex_gate(study: Study, patient: PatientProfile) -> GateResult:
    if study.sex == "ALL":
        return GateResult(name="sex", passed=True, evidence="Study accepts all sexes.")
    if patient.sex is None:
        return GateResult(
            name="sex", passed=False, evidence=f"Study requires {study.sex}; patient sex is not recorded."
        )
    ok = patient.sex == study.sex
    return GateResult(
        name="sex",
        passed=ok,
        evidence=f"Study requires {study.sex}; patient is {patient.sex}.",
    )


def _age_gate(study: Study, patient: PatientProfile, as_of: date) -> GateResult:
    try:
        lo = parse_age_to_months(study.min_age)
        hi = parse_age_to_months(study.max_age)
    except ValueError as exc:
        return GateResult(name="age", passed=False, evidence=f"{exc}. Manual review required.")
    if lo is None and hi is None:
        return GateResult(name="age", passed=True, evidence="Study has no age restriction.")
    months = patient.age_in_months(as_of)
    if months is None:
        return GateResult(name="age", passed=False, evidence="Patient birth date not recorded; cannot verify age.")
    ok = (lo is None or months >= lo) and (hi is None or months <= hi)
    lo_text = study.min_age if lo is not None else "no minimum"
    hi_text = study.max_age if hi is not None else "no maximum"
    bounds = f"{lo_text} to {hi_text}"
    return GateResult(
        name="age",
        passed=ok,
        evidence=f"Patient is {_format_age(months)} old; study allows {bounds}.",
    )


def _condition_gate(study: Study, patient: PatientProfile) -> GateResult:
    if not study.conditions:
        return GateResult(name="condition", passed=False, evidence="Study lists no target conditions.")

    active = [c for c in patient.conditions if c.active]
    active_codes = patient.snomed_codes(active_only=True)
    hits: set[str] = set()

    for study_condition in study.conditions:
        for disease in find_diseases(study_condition):
            matched = disease.snomed & active_codes
            if matched:
                hits.add(f"{disease.name} (SNOMED {sorted(matched)[0]})")
            elif any(c.display and disease.mentioned_in(c.display) for c in active):
                hits.add(f"{disease.name} (matched by condition text)")
        # Fallback for conditions outside the dictionary: plain normalized text containment.
        sc = normalize(study_condition)
        for c in active:
            pc = normalize(c.display)
            if pc and (pc in sc or sc in pc):
                hits.add(f"{c.display} (matched by condition text)")

    if hits:
        evidence = "Active condition match: " + "; ".join(sorted(hits)) + "."
        return GateResult(name="condition", passed=True, evidence=evidence)
    return GateResult(
        name="condition",
        passed=False,
        evidence="No active patient condition matches study conditions: " + ", ".join(study.conditions) + ".",
    )


def run_gates(study: Study, patient: PatientProfile, as_of: date) -> list[GateResult]:
    return [
        _status_gate(study),
        _sex_gate(study, patient),
        _age_gate(study, patient, as_of),
        _condition_gate(study, patient),
    ]
