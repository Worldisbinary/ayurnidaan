import pytest
from fastapi.testclient import TestClient

from ayurnidaan import api
from ayurnidaan.config import Settings
from ayurnidaan.service import AnalyticsService, get_service


@pytest.fixture(scope="module")
def client(synthetic_settings, pipeline_run):
    svc = AnalyticsService(synthetic_settings)
    api.app.dependency_overrides[get_service] = lambda: svc
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def test_health(client, pipeline_run):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["run_id"] == pipeline_run["run_id"]


def test_kpis(client):
    k = client.get("/v1/kpis").json()
    assert k["patients"] == 700 and k["sources_rejected"] == 0


def test_cluster_detail_and_404(client):
    assert client.get("/v1/clusters/0").status_code == 200
    assert client.get("/v1/clusters/999").status_code == 404


def test_adaptive_screening_flow(client):
    r = client.post(
        "/v1/screening/next", json={"answers": {"cough": True, "wheezing": True}}
    ).json()
    assert r["top_body_systems"][0]["body_system"] == "respiratory"
    # Modern-KB profiles carry no body system ("unspecified"); none may be another system.
    assert r["matching_conditions"]
    assert {m["body_system"] for m in r["matching_conditions"]} <= {"respiratory", "unspecified"}


def test_unknown_symptoms_are_reported_not_fatal(client):
    r = client.post("/v1/screening/next", json={"answers": {"not a symptom": True}}).json()
    assert r["ignored_unknown_symptoms"] == ["not a symptom"]


def test_risk_score_with_reasons(client):
    r = client.post("/v1/risk/score", json={"age": 70, "family_history": "yes", "sleep_hours": 6})
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["probability"] <= 1
    assert body["reasons"] and {"variable", "log_odds", "direction"} <= set(body["reasons"][0])


@pytest.mark.parametrize(
    "payload",
    [
        {"age": 300, "family_history": "yes", "sleep_hours": 6},
        {"age": 40, "family_history": "maybe", "sleep_hours": 6},
        {"age": 40, "family_history": "no", "sleep_hours": 30},
    ],
)
def test_risk_score_validation(client, payload):
    assert client.post("/v1/risk/score", json=payload).status_code == 422


def test_api_key_enforced_when_configured(client, monkeypatch):
    monkeypatch.setattr(api, "get_settings", lambda: Settings(api_key="s3cret"))
    assert client.get("/v1/kpis").status_code == 401
    assert client.get("/v1/kpis", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/v1/kpis", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/health").status_code == 200  # liveness stays open
