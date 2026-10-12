import json

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
def client(ctgov):
    app.dependency_overrides[get_repository] = lambda: FakeRepo(ctgov)
    yield TestClient(app)
    app.dependency_overrides.clear()


def form(bundle, **extra):
    data = {"bundleText": json.dumps(bundle), "asOf": "2026-10-12"}
    data.update(extra)
    return data


def test_index_serves_ui(client):
    html = client.get("/").text
    assert 'src="/static/htmx.min.js"' in html
    assert 'hx-post="/match-ui"' in html


def test_sample_bundle_prefills_textarea(client):
    html = client.get("/sample-bundle").text
    assert "<textarea" in html and "resourceType" in html


def test_static_htmx_is_served(client):
    assert client.get("/static/htmx.min.js").status_code == 200


def test_match_ui_renders_results_with_register_button(client, bundle):
    r = client.post("/match-ui", data=form(bundle))
    assert r.status_code == 200
    assert "NCT04551066" in r.text and "POTENTIAL" in r.text
    assert "Register candidate" in r.text
    assert 'name="patientId" value="pt-001"' in r.text


def test_match_ui_accepts_file_upload(client, bundle):
    r = client.post(
        "/match-ui",
        data={"asOf": "2026-10-12"},
        files={"bundleFile": ("bundle.json", json.dumps(bundle).encode(), "application/json")},
    )
    assert r.status_code == 200
    assert "NCT04551066" in r.text


def test_match_ui_include_ineligible_lists_gate_failures(client, bundle):
    r = client.post("/match-ui", data=form(bundle, includeIneligible="true"))
    assert all(nct in r.text for nct in ("NCT04551066", "NCT05000002", "NCT05000003"))
    assert "INELIGIBLE" in r.text


def test_match_ui_invalid_json_shows_error(client):
    r = client.post("/match-ui", data={"bundleText": "{not json"})
    assert "not valid JSON" in r.text


def test_match_ui_empty_form_shows_error(client):
    r = client.post("/match-ui", data={})
    assert "Paste a FHIR Bundle JSON" in r.text


def test_match_ui_patient_without_active_conditions_shows_error(client, bundle):
    bundle["entry"] = bundle["entry"][:1]
    assert "no active conditions" in client.post("/match-ui", data=form(bundle)).text


def test_register_ui_is_idempotent(client):
    data = {"patientId": "pt-001", "nctId": "NCT04551066"}
    first = client.post("/candidates-ui", data=data).text
    second = client.post("/candidates-ui", data=data).text
    assert "Registered" in first and "already existed" in second
    assert first.split("code>")[1].split("</code")[0] in second


def test_register_ui_rejects_bad_nct_id(client):
    r = client.post("/candidates-ui", data={"patientId": "pt-001", "nctId": "12345"})
    assert "NCT id" in r.text
