"""Offline demo: run the engine on the bundled sample patient + sample ClinicalTrials.gov payload.

    python scripts/demo.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.fhir_study import from_research_study, to_research_study  # noqa: E402
from app.matcher import evaluate  # noqa: E402
from app.patient import parse_bundle  # noqa: E402


def main() -> None:
    patient = parse_bundle(json.loads((ROOT / "samples/patient_bundle.json").read_text()))
    raw = json.loads((ROOT / "samples/ctgov_parkinson.json").read_text())
    as_of = date(2026, 10, 12)
    for study_json in raw["studies"]:
        study = from_research_study(to_research_study(study_json))
        result = evaluate(study, patient, as_of)
        print(json.dumps(result.model_dump(by_alias=True, mode="json"), indent=2))


if __name__ == "__main__":
    main()
