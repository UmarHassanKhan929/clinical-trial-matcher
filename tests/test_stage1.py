import time
from dataclasses import replace
from datetime import date

import pytest

from app.patient import PatientProfile
from app.stage1 import parse_age_to_months, run_gates


def gate(gates, name):
    return next(g for g in gates if g.name == name)


@pytest.mark.parametrize(
    "raw, expected",
    [("18 Years", 216.0), ("6 Months", 6.0), ("1 Year", 12.0), (" 2 years ", 24.0), ("N/A", None), (None, None)],
)
def test_parse_age(raw, expected):
    assert parse_age_to_months(raw) == expected


def test_parse_age_rejects_garbage():
    with pytest.raises(ValueError):
        parse_age_to_months("adults only")


def test_all_gates_pass_for_matching_patient(make_study, patient, as_of):
    gates = run_gates(make_study(), patient, as_of)
    assert all(g.passed for g in gates), [g for g in gates if not g.passed]


def test_non_recruiting_study_fails(make_study, patient, as_of):
    gates = run_gates(make_study(ctgov_status="NOT_YET_RECRUITING"), patient, as_of)
    assert not gate(gates, "recruitmentStatus").passed


def test_sex_gate(make_study, patient, as_of):
    assert gate(run_gates(make_study(sex="MALE"), patient, as_of), "sex").passed
    assert not gate(run_gates(make_study(sex="FEMALE"), patient, as_of), "sex").passed


def test_sex_gate_fails_closed_when_patient_sex_unknown(make_study, patient, as_of):
    unknown_sex = replace(patient, sex=None)
    assert not gate(run_gates(make_study(sex="FEMALE"), unknown_sex, as_of), "sex").passed
    assert gate(run_gates(make_study(sex="ALL"), unknown_sex, as_of), "sex").passed


def test_age_gate_boundaries(make_study, patient):
    study = make_study(min_age="68 Years", max_age="68 Years")
    assert gate(run_gates(study, patient, date(2026, 3, 14)), "age").passed  # exactly 68y0m
    assert not gate(run_gates(study, patient, date(2026, 3, 13)), "age").passed  # 67y11m
    assert not gate(run_gates(study, patient, date(2027, 4, 14)), "age").passed  # 69y1m


def test_age_gate_in_months(make_study, as_of):
    infant = PatientProfile("p", "MALE", date(2026, 3, 1), (), ())  # 7 months old
    study = make_study(min_age="6 Months", max_age="12 Months")
    assert gate(run_gates(study, infant, as_of), "age").passed


def test_age_gate_requires_birth_date(make_study, patient, as_of):
    gates = run_gates(make_study(), replace(patient, birth_date=None), as_of)
    assert not gate(gates, "age").passed


def test_condition_gate_matches_by_snomed(make_study, patient, as_of):
    g = gate(run_gates(make_study(conditions=("Parkinson Disease",)), patient, as_of), "condition")
    assert g.passed and "49049000" in g.evidence


def test_condition_gate_rejects_unrelated_condition(make_study, patient, as_of):
    g = gate(run_gates(make_study(conditions=("Breast Cancer",)), patient, as_of), "condition")
    assert not g.passed


def test_condition_gate_ignores_resolved_conditions(make_study, bundle, as_of):
    from app.patient import parse_bundle

    bundle["entry"][1]["resource"]["clinicalStatus"]["coding"][0]["code"] = "resolved"
    g = gate(run_gates(make_study(), parse_bundle(bundle), as_of), "condition")
    assert not g.passed


def test_condition_gate_text_fallback_for_non_dictionary_conditions(make_study, patient, as_of):
    from app.patient import Condition

    rare = replace(patient, conditions=(Condition(None, None, "Essential tremor", True),))
    g = gate(run_gates(make_study(conditions=("Essential Tremor",)), rare, as_of), "condition")
    assert g.passed


def test_acceptance_ineligible_rejected_under_10ms(make_study, patient, as_of):
    """Acceptance criterion 2: Stage 1 rejection takes < 10 ms (best of 50 to avoid CI noise)."""
    study = make_study(sex="FEMALE")
    timings = []
    for _ in range(50):
        t0 = time.perf_counter()
        gates = run_gates(study, patient, as_of)
        timings.append(time.perf_counter() - t0)
        assert not all(g.passed for g in gates)
    assert min(timings) < 0.010
