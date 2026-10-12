## Where to go next (pick any for follow-up commits)

| Idea | What you learn |
| --- | --- |
| Test against **Synthea** synthetic patients (generate FHIR bundles) | Realistic FHIR data and `urn:uuid` references |
| Replace `vocab.py` with a **terminology service** call (`$expand`, `$subsumes`) | How production code resolves SNOMED hierarchies |
| Add **unit conversion** (µmol/L ↔ mg/dL) | Why units are a patient-safety topic |
| Add **temporal rules** ("within 30 days of screening") | The hardest part of real criteria |
| Persist `ResearchSubject` in a **HAPI FHIR** server (Docker image available) | Real FHIR REST: `PUT`, conditional create |
| Add **medication criteria** from `MedicationStatement` / RxNorm | Another major code system |
| Add an **audit log** (input hash, `asOf`, rule versions) | What "legally defensible" requires |
| Benchmark Stage 1 with `pytest-benchmark` | Evidence for the 10 ms claim at scale |

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `ModuleNotFoundError: app` when running pytest | Run from the repo root; `pyproject.toml` sets `pythonpath = ["."]` |
| `/match` returns 502 | The server cannot reach `clinicaltrials.gov` (offline, proxy, firewall) |
| `/match` returns 422 "no active conditions" | The bundle has no active `Condition` resources |
| A criterion you expected to be evaluated shows `UNKNOWN` | No rule covers it. That is by design; add a rule plus a test |
| A lab shows `UNKNOWN` "Unit mismatch" | Criterion and chart units differ; no conversion is performed |
| Results change between runs | You omitted `asOf`; the date defaults to today |

## Known limits and honest caveats

- The disease and lab dictionaries are a **starter set**. Treat every code as "verify before use".
- Sample trial data is **synthetic**. The NCT id from your README was reused for the first study for continuity, but its title and criteria here are invented, not the real registry record.
- The README's original example used SNOMED `63650001` for Parkinson's disease. The project uses `49049000`, which is the code I believe is correct for Parkinson's disease; confirm it in the SNOMED CT browser before you rely on it.
- Everything in the test suite is verified offline. The live ClinicalTrials.gov request path is exercised through a mocked transport; run it once yourself on your own machine to confirm real-world payloads parse as expected.
- This is a learning project, not clinical software.
