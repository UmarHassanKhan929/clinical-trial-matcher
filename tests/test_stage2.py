from dataclasses import replace
from datetime import date

import pytest

from app.patient import Condition, Observation
from app.schemas import CriterionType, Status
from app.stage2 import evaluate_criteria, split_criteria

INC, EXC = CriterionType.INCLUSION, CriterionType.EXCLUSION


def one(text, patient, as_of, header="Inclusion Criteria:"):
    return evaluate_criteria(f"{header}\n* {text}", patient, as_of)[0]


# ----------------------------------------------------------------------------- splitting


def test_split_inclusion_exclusion_and_continuations():
    text = "Inclusion Criteria:\n\n* Age 18+\n* Has a long\n  wrapped line\n\nExclusion Criteria:\n- Pregnant\n"
    assert split_criteria(text) == [
        (INC, "Age 18+"),
        (INC, "Has a long wrapped line"),
        (EXC, "Pregnant"),
    ]


def test_split_handles_numbered_lists_and_missing_headers():
    assert split_criteria("1. First\n2) Second") == [(INC, "First"), (INC, "Second")]


# ----------------------------------------------------------------------------- age


@pytest.mark.parametrize(
    "text, status",
    [
        ("Age 50 to 80 years at screening", Status.MET),
        ("Aged 18-75 years", Status.MET),
        ("Aged 18-65 years", Status.NOT_MET),
        ("Age >= 18 years", Status.MET),
        ("Age ≥ 70 years", Status.NOT_MET),
        ("At least 75 years of age", Status.NOT_MET),
        ("18 years or older", Status.MET),
        ("Age under 65 years", Status.NOT_MET),
    ],
)
def test_age_rule_inclusion(text, status, patient, as_of):
    assert one(text, patient, as_of).status is status


def test_age_rule_exclusion_flips_status(patient, as_of):
    r = one("Age > 75 years", patient, as_of, header="Exclusion Criteria:")
    assert r.status is Status.MET  # 68 is not > 75 => not excluded
    r = one("Age > 60 years", patient, as_of, header="Exclusion Criteria:")
    assert r.status is Status.NOT_MET and r.evidence.startswith("Exclusion applies.")


def test_age_evidence_cites_chart(patient, as_of):
    assert "Patient is 68 years old" in one("Age 50 to 80 years", patient, as_of).evidence


def test_age_unknown_without_birth_date(patient, as_of):
    r = one("Age 50 to 80 years", replace(patient, birth_date=None), as_of)
    assert r.status is Status.UNKNOWN


def test_age_cue_without_numbers_falls_through_to_unknown(patient, as_of):
    assert one("Women of childbearing age", patient, as_of).status is Status.UNKNOWN


# ----------------------------------------------------------------------------- labs


def lab(value, unit, on, loinc="2160-0"):
    return Observation(loinc=loinc, display="", value=value, unit=unit, on=on)


def with_obs(patient, *obs):
    return replace(patient, observations=tuple(obs))


def test_lab_exclusion_triggered(patient, as_of):
    p = with_obs(patient, lab(2.4, "mg/dL", date(2026, 9, 1)))
    r = one("Serum creatinine > 1.8 mg/dL", p, as_of, header="Exclusion Criteria:")
    assert r.status is Status.NOT_MET
    assert "2.4 mg/dL" in r.evidence and "2026-09-01" in r.evidence


def test_lab_exclusion_not_triggered(patient, as_of):
    p = with_obs(patient, lab(1.0, "mg/dL", date(2026, 9, 1)))
    assert one("Serum creatinine > 1.8 mg/dL", p, as_of, header="Exclusion Criteria:").status is Status.MET


def test_lab_boundary_is_strict(patient, as_of):
    p = with_obs(patient, lab(1.8, "mg/dL", date(2026, 9, 1)))
    assert one("Creatinine > 1.8 mg/dL", p, as_of, header="Exclusion Criteria:").status is Status.MET
    assert one("Creatinine >= 1.8 mg/dL", p, as_of, header="Exclusion Criteria:").status is Status.NOT_MET


def test_lab_missing_is_unknown(patient, as_of):
    r = one("Serum creatinine > 1.8 mg/dL", patient, as_of, header="Exclusion Criteria:")
    assert r.status is Status.UNKNOWN and "Manual review required" in r.evidence


def test_lab_stale_is_unknown(patient, as_of):
    p = with_obs(patient, lab(1.0, "mg/dL", date(2025, 1, 1)))
    r = one("Serum creatinine > 1.8 mg/dL", p, as_of, header="Exclusion Criteria:")
    assert r.status is Status.UNKNOWN and "days old" in r.evidence


def test_lab_unit_mismatch_is_unknown_not_converted(patient, as_of):
    p = with_obs(patient, lab(212.0, "umol/L", date(2026, 9, 1)))
    r = one("Serum creatinine > 1.8 mg/dL", p, as_of, header="Exclusion Criteria:")
    assert r.status is Status.UNKNOWN and "Unit mismatch" in r.evidence


def test_lab_uses_latest_observation(patient, as_of):
    p = with_obs(patient, lab(3.0, "mg/dL", date(2026, 1, 1)), lab(1.0, "mg/dL", date(2026, 9, 1)))
    assert one("Creatinine > 1.8 mg/dL", p, as_of, header="Exclusion Criteria:").status is Status.MET


def test_lab_between_inclusion(patient, as_of):
    r = one("HbA1c between 6.5 and 9.0 %", patient, as_of)
    assert r.status is Status.MET  # sample patient HbA1c is 6.8 %


def test_lab_longest_name_wins(patient, as_of):
    """'hemoglobin a1c' must not be read as plain 'hemoglobin'."""
    assert "HbA1c" in one("Hemoglobin A1c < 7%", patient, as_of).evidence


# ----------------------------------------------------------------------------- conditions


def test_condition_inclusion_met_uses_snomed(patient, as_of):
    r = one("Diagnosis of Parkinson's Disease", patient, as_of)
    assert r.status is Status.MET and "49049000" in r.evidence


def test_condition_explicit_snomed_code_in_text(patient, as_of):
    r = one("Diagnosis of Parkinson's Disease (SNOMED 49049000)", patient, as_of)
    assert r.status is Status.MET
    assert one("Diagnosis of something (SNOMED 63650001)", patient, as_of).status is Status.NOT_MET


def test_condition_inclusion_not_met(patient, as_of):
    r = one("Type 2 diabetes mellitus", patient, as_of)
    assert r.status is Status.NOT_MET and "found in chart" in r.evidence


def test_condition_exclusion_checks_history_including_resolved(patient, as_of):
    resolved_stroke = Condition("230690007", "http://snomed.info/sct", "Stroke", active=False)
    p = replace(patient, conditions=patient.conditions + (resolved_stroke,))
    r = one("History of ischemic stroke", p, as_of, header="Exclusion Criteria:")
    assert r.status is Status.NOT_MET and "230690007" in r.evidence


def test_condition_exclusion_absent_is_met(patient, as_of):
    r = one("History of ischemic stroke", patient, as_of, header="Exclusion Criteria:")
    assert r.status is Status.MET and "found in chart" in r.evidence


def test_condition_inclusion_requires_active_status(patient, as_of):
    inactive = replace(patient, conditions=(Condition("44054006", "http://snomed.info/sct", "T2DM", False),))
    assert one("Type 2 diabetes", inactive, as_of).status is Status.NOT_MET


def test_negation_is_unknown(patient, as_of):
    r = one("No history of hypertension", patient, as_of)
    assert r.status is Status.UNKNOWN and "negation" in r.evidence


def test_compound_condition_without_or_is_unknown(patient, as_of):
    assert one("Diabetes and hypertension", patient, as_of).status is Status.UNKNOWN


def test_compound_condition_with_or_matches_any(patient, as_of):
    r = one("History of stroke or hypertension", patient, as_of, header="Exclusion Criteria:")
    assert r.status is Status.NOT_MET  # patient has hypertension


# ----------------------------------------------------------------------------- fallback


def test_unrecognized_line_is_unknown(patient, as_of):
    r = one("Willing to provide informed consent", patient, as_of)
    assert r.status is Status.UNKNOWN and "Manual review" in r.evidence


def test_every_result_has_evidence(patient, as_of, ctgov):
    text = ctgov["studies"][0]["protocolSection"]["eligibilityModule"]["eligibilityCriteria"]
    results = evaluate_criteria(text, patient, as_of)
    assert len(results) == 7
    assert all(r.evidence.strip() for r in results)  # acceptance criterion 3
