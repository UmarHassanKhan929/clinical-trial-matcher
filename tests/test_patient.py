from datetime import date

import pytest

from app.patient import parse_bundle


def test_parses_patient_basics(patient):
    assert patient.id == "pt-001"
    assert patient.sex == "MALE"
    assert patient.birth_date == date(1958, 3, 14)
    assert patient.snomed_codes(active_only=True) == {"49049000", "38341003"}


def test_age_in_months_respects_day_of_month(patient):
    assert patient.age_in_months(date(2026, 3, 13)) == 67 * 12 + 11  # day before 68th birthday
    assert patient.age_in_months(date(2026, 3, 14)) == 68 * 12


def test_latest_observation_ignores_future_dates(patient):
    assert patient.latest_observation(("4548-4",), date(2026, 5, 31)) is None
    assert patient.latest_observation(("4548-4",), date(2026, 6, 1)).value == 6.8


def test_rejects_non_bundle():
    with pytest.raises(ValueError, match="Bundle"):
        parse_bundle({"resourceType": "Patient"})


def test_requires_exactly_one_patient():
    with pytest.raises(ValueError, match="exactly one Patient"):
        parse_bundle({"resourceType": "Bundle", "entry": []})


def test_partial_birth_date_is_unknown_not_guessed(bundle):
    bundle["entry"][0]["resource"]["birthDate"] = "1958"
    assert parse_bundle(bundle).birth_date is None


def test_entered_in_error_condition_is_dropped(bundle):
    bundle["entry"][1]["resource"]["verificationStatus"] = {"coding": [{"code": "entered-in-error"}]}
    assert "49049000" not in parse_bundle(bundle).snomed_codes(active_only=False)


def test_resolved_condition_is_inactive(bundle):
    bundle["entry"][1]["resource"]["clinicalStatus"]["coding"][0]["code"] = "resolved"
    p = parse_bundle(bundle)
    assert "49049000" not in p.snomed_codes(active_only=True)
    assert "49049000" in p.snomed_codes(active_only=False)


def test_other_patients_resources_are_ignored(bundle):
    bundle["entry"][1]["resource"]["subject"] = {"reference": "Patient/someone-else"}
    assert "49049000" not in parse_bundle(bundle).snomed_codes(active_only=False)


def test_urn_uuid_references_supported(bundle):
    bundle["entry"][0]["fullUrl"] = "urn:uuid:abc"
    bundle["entry"][1]["resource"]["subject"] = {"reference": "urn:uuid:abc"}
    assert "49049000" in parse_bundle(bundle).snomed_codes(active_only=True)
