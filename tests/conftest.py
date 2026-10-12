import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from app.patient import PatientProfile, parse_bundle

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
AS_OF = date(2026, 10, 12)


@pytest.fixture
def as_of() -> date:
    return AS_OF


@pytest.fixture
def bundle() -> dict:
    return json.loads((SAMPLES / "patient_bundle.json").read_text())


@pytest.fixture
def ctgov() -> dict:
    return json.loads((SAMPLES / "ctgov_parkinson.json").read_text())


@pytest.fixture
def patient(bundle) -> PatientProfile:
    return parse_bundle(bundle)


@pytest.fixture
def make_study():
    """Factory: a RECRUITING Parkinson study that passes every gate, with overrides."""
    from app.fhir_study import Study  # imported lazily so early build steps can run their own tests

    base = Study(
        nct_id="NCT00000001",
        title="Test Study",
        ctgov_status="RECRUITING",
        conditions=("Parkinson Disease",),
        eligibility_text="",
        sex="ALL",
        min_age="18 Years",
        max_age="N/A",
    )

    def _make(**overrides) -> Study:
        return replace(base, **overrides)

    return _make
