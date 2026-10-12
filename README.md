# Clinical Trial Matcher

A deterministic, explainable clinical trial prescreening engine built for HL7 FHIR R4 and ClinicalTrials.gov API v2.

[![CI](https://github.com/UmarHassanKhan929/clinical-trial-matcher/actions/workflows/ci.yml/badge.svg)](https://github.com/UmarHassanKhan929/clinical-trial-matcher/actions)

![Offline demo on bundled sample data](docs/demo.gif)

> **Educational / portfolio project. Not a medical device and not for clinical use.** It uses a small starter terminology dictionary and synthetic sample data. Never commit real patient data (PHI).

---

## Why

Most clinical trials miss enrollment deadlines, and slow, manual chart prescreening is a major reason. LLMs are a poor fit for the eligibility decision itself: they can hallucinate eligibility, are unreliable on numeric boundaries (age, lab ranges), and cannot give an IRB-grade audit trail. This engine makes every decision with plain rules, so the same input always gives the same output, and every line carries the chart evidence behind it.

## Architecture

```
ClinicalTrials.gov v2 ──► Ingestion (3 req/s limiter, 12 h TTL cache)
                              │  normalize
                              ▼
                     FHIR R4 ResearchStudy
                              │
FHIR Bundle (Patient,         ▼
Condition, Observation) ─► Stage 1: hard gates ── fail ──► INELIGIBLE (no Stage 2)
                              │ pass   status · sex · age · condition (SNOMED CT)
                              ▼
                     Stage 2: criteria evaluator
                     inclusion/exclusion lines ► MET / NOT_MET / UNKNOWN + evidence
                              │
                              ▼
                     Roll-up: verdict + score ──► POST /candidates ► ResearchSubject
```

| Module | Responsibility |
| --- | --- |
| `app/ingestion.py` | Rate limiter, TTL cache, ClinicalTrials.gov client (FR-1) |
| `app/fhir_study.py` | CT.gov JSON ⇄ FHIR `ResearchStudy` (FR-2) |
| `app/patient.py` | FHIR Bundle → patient profile |
| `app/stage1.py` | Boolean hard gates (FR-3) |
| `app/stage2.py` | Criteria splitting + regex rules (FR-4) |
| `app/scoring.py` | Verdict + score (FR-5) |
| `app/main.py` | FastAPI endpoints, idempotent `ResearchSubject` (FR-6) |

## Output contract

`POST /match` returns, per study (trimmed example from `scripts/demo.py`):

```json
{
  "nctId": "NCT04551066",
  "title": "Disease-Modifying Therapy in Early Parkinson's Disease",
  "verdict": "POTENTIAL",
  "score": 0.79,
  "hardGatesPassed": true,
  "gates": [
    {"name": "age", "passed": true, "evidence": "Patient is 68 years old; study allows 40 Years to 85 Years."}
  ],
  "criteria": [
    {"type": "INCLUSION", "text": "Age 50 to 80 years at screening", "status": "MET",
     "evidence": "Patient is 68 years old (criterion: age 50 to 80 years)."},
    {"type": "EXCLUSION", "text": "History of ischemic stroke", "status": "MET",
     "evidence": "No Stroke (SNOMED 230690007, 422504002) found in chart."},
    {"type": "EXCLUSION", "text": "Serum creatinine > 1.8 mg/dL", "status": "UNKNOWN",
     "evidence": "No Serum creatinine observation (LOINC 2160-0, 38483-4) on or before 2026-10-12. Manual review required."}
  ]
}
```

**What the statuses mean:** `MET` = the patient satisfies the requirement. For an *exclusion* line, `MET` means the patient does **not** have the excluded property; `NOT_MET` means the exclusion applies.

**Verdict:** any `NOT_MET` → `INELIGIBLE`; otherwise any `UNKNOWN` → `POTENTIAL`; otherwise `ELIGIBLE`.
**Score:** `(MET + 0.5 × UNKNOWN) / total criteria`. Stage 1 failures score `0.0`.

## Quickstart

Prerequisites: Python 3.11+ (Docker optional).

```bash
git clone https://github.com/your-org/clinical-trial-matcher.git
cd clinical-trial-matcher
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

pytest -v                  # run the test suite
python scripts/demo.py     # offline demo on bundled sample data
uvicorn app.main:app --reload   # API + docs at http://localhost:8000/docs
```

Docker:

```bash
docker build -t clinical-trial-matcher .
docker run -p 8000:8000 clinical-trial-matcher
```

Call the API (this one reaches ClinicalTrials.gov):

```bash
curl -s localhost:8000/match \
  -H 'Content-Type: application/json' \
  -d "{\"bundle\": $(cat samples/patient_bundle.json), \"asOf\": \"2026-10-12\"}" | python -m json.tool

curl -s localhost:8000/candidates -H 'Content-Type: application/json' \
  -d '{"patientId": "pt-001", "nctId": "NCT04551066"}'      # 201, then 200 on repeats
```

Pass `asOf` for reproducible runs. If omitted, today's date is used and echoed back in the response.

## Design decisions

- **Input is a FHIR Bundle**, not a bare Patient: eligibility needs Conditions and Observations, not just demographics.
- **Fail closed, say UNKNOWN.** Missing data, stale labs (> 365 days), unit mismatches, negation and compound conditions all become `UNKNOWN` for a human, never a guess.
- **Original CT.gov status is kept** in a `ResearchStudy` extension, because FHIR's `status` is coarser (RECRUITING and ENROLLING_BY_INVITATION both map to `active`).
- **Deterministic ids:** `ResearchSubject` ids are UUIDv5 of `patient|trial`, which makes registration idempotent.

## Limitations

- **Starter terminology:** ~13 diseases and ~10 lab tests. Production needs a terminology service (SNOMED/LOINC value sets, UMLS).
- **Negation nuance:** Free-text criteria containing negation or compound logic return `UNKNOWN` for coordinator review.
- **Temporal context:** Only a simple recency rule exists (latest lab within 365 days). Rules like "event within past 30 days" are not evaluated.
- **No unit conversion:** a µmol/L result against an mg/dL criterion is `UNKNOWN`.
- **Closed-world assumption:** an absent condition is treated as "not in chart", which can be wrong if the record is incomplete.
- **Human-in-the-loop:** All `POTENTIAL` matches require human clinical sign-off prior to subject enrollment.
- **In-memory state:** the cache and `ResearchSubject` store reset on restart.

## Project layout

```
app/        service code          tests/     pytest suite (unit + API)
samples/    synthetic FHIR + CT.gov-shaped data
scripts/    offline demo          docs/      step-by-step build guide
```

## License

MIT
