import httpx
import pytest
from fastapi.testclient import TestClient

from app.fhir_study import to_research_study
from app.main import app, get_repository


class FakeRepo:
    def __init__(self, ctgov):
        self.calls: list[str] = []
        self._studies = [to_research_study(s) for s in ctgov["studies"]]

    async def recruiting_for(self, condition):
        self.calls.append(condition)
        return list(self._studies)


@pytest.fixture
def repo(ctgov):
    fake = FakeRepo(ctgov)
    app.dependency_overrides[get_repository] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client(repo):
    return TestClient(app)


def body(bundle):
    return {"bundle": bundle, "asOf": "2026-10-12"}


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_match_returns_only_viable_studies_sorted(client, bundle):
    r = client.post("/match", json=body(bundle))
    assert r.status_code == 200
    data = r.json()
    assert data["patientId"] == "pt-001" and data["asOf"] == "2026-10-12"
    assert [m["nctId"] for m in data["results"]] == ["NCT04551066"]
    top = data["results"][0]
    assert top["verdict"] == "POTENTIAL" and top["score"] == 0.79 and top["hardGatesPassed"] is True
    assert all(c["evidence"] for c in top["criteria"])


def test_include_ineligible_shows_gate_failures_with_evidence(client, bundle):
    r = client.post("/match?includeIneligible=true", json=body(bundle))
    results = {m["nctId"]: m for m in r.json()["results"]}
    assert set(results) == {"NCT04551066", "NCT05000002", "NCT05000003"}
    assert [m["nctId"] for m in r.json()["results"]][0] == "NCT04551066"  # best match first
    female_only = results["NCT05000002"]
    assert female_only["verdict"] == "INELIGIBLE" and female_only["criteria"] == []
    assert any(g["name"] == "sex" and not g["passed"] and g["evidence"] for g in female_only["gates"])


def test_acceptance_identical_input_gives_identical_output(client, bundle):
    """Acceptance criterion 1: same patient + same trial data => exact same verdict and score."""
    runs = [client.post("/match?includeIneligible=true", json=body(bundle)).json() for _ in range(25)]
    assert all(run == runs[0] for run in runs)


def test_searches_each_active_condition(client, repo, bundle):
    client.post("/match", json=body(bundle))
    assert repo.calls == ["Hypertension", "Parkinson's disease"]


def test_invalid_bundle_is_422(client):
    r = client.post("/match", json={"bundle": {"resourceType": "Patient"}})
    assert r.status_code == 422


def test_patient_without_active_conditions_is_422(client, bundle):
    bundle["entry"] = bundle["entry"][:1]
    assert client.post("/match", json=body(bundle)).status_code == 422


def test_upstream_failure_is_502(bundle):
    class Broken:
        async def recruiting_for(self, condition):
            raise httpx.ConnectError("boom")

    app.dependency_overrides[get_repository] = lambda: Broken()
    try:
        assert TestClient(app).post("/match", json=body(bundle)).status_code == 502
    finally:
        app.dependency_overrides.clear()


def test_registration_is_idempotent(client):
    payload = {"patientId": "pt-001", "nctId": "NCT04551066"}
    first = client.post("/candidates", json=payload)
    second = client.post("/candidates", json=payload)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json() == second.json()
    subject = first.json()
    assert subject["resourceType"] == "ResearchSubject" and subject["status"] == "candidate"
    assert subject["study"] == {"reference": "ResearchStudy/NCT04551066"}
    assert subject["individual"] == {"reference": "Patient/pt-001"}


def test_registration_ids_differ_per_pair(client):
    a = client.post("/candidates", json={"patientId": "p1", "nctId": "NCT00000001"}).json()["id"]
    b = client.post("/candidates", json={"patientId": "p1", "nctId": "NCT00000002"}).json()["id"]
    assert a != b


def test_registration_validates_nct_id(client):
    assert client.post("/candidates", json={"patientId": "p", "nctId": "12345"}).status_code == 422
