import uuid

import pytest
from fastapi.testclient import TestClient

from ayurnidaan.app import services
from ayurnidaan.app.main import create_app
from ayurnidaan.clinical import red_flags
from ayurnidaan.config import Settings

NO_FLAGS = {f.code: False for f in red_flags.CHECKLIST}
PW = "correct-horse-battery"


@pytest.fixture(scope="module")
def client(synthetic_settings, pipeline_run, tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "app.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{db.as_posix()}",
        knowledge_dir=synthetic_settings.knowledge_dir,
        bootstrap_admin_email="admin@test.ayurnidaan.in",
    )
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture(autouse=True)
def fake_climate(monkeypatch):
    def fake(url, timeout=20):
        if "archive" in url:
            return {
                "daily": {
                    "precipitation_sum": [0.6] * 365,
                    "relative_humidity_2m_mean": [50] * 365,
                    "temperature_2m_mean": [26] * 365,
                }
            }
        return {
            "results": [
                {
                    "name": "Pilani",
                    "admin1": "Rajasthan",
                    "admin2": "Jhunjhunu",
                    "country_code": "IN",
                    "latitude": 28.36,
                    "longitude": 75.6,
                }
            ]
        }

    monkeypatch.setattr(services, "_http_json", fake)


def register(c, role="patient", email=None, **extra) -> dict:
    email = email or f"{role}-{uuid.uuid4().hex[:8]}@test.ayurnidaan.in"
    r = c.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PW, "full_name": f"Test {role}", "role": role, **extra},
    )
    assert r.status_code == 201, r.text
    return {
        "Authorization": f"Bearer {r.json()['access_token']}",
        "_refresh": r.json()["refresh_token"],
        "_email": email,
    }


def H(h):
    return {k: v for k, v in h.items() if not k.startswith("_")}


def patient_with_case(c, consent=("care",), symptoms=None) -> tuple[dict, str]:
    p = register(c)
    c.put("/api/v1/me/profile", headers=H(p), json={"date_of_birth": "1985-02-01", "sex": "female"})
    for purpose in consent:
        c.post("/api/v1/me/consents", headers=H(p), json={"purpose": purpose, "granted": True})
    r = c.post(
        "/api/v1/encounters",
        headers=H(p),
        json={
            "red_flag_checklist": NO_FLAGS,
            "chief_complaint": "cough for a week",
            "symptoms": symptoms or {"cough": True, "wheezing": True},
        },
    )
    assert r.status_code == 201, r.text
    return p, r.json()["id"]


@pytest.fixture(scope="module")
def admin(client):
    return register(client, email="admin@test.ayurnidaan.in")


@pytest.fixture(scope="module")
def doctor(client, admin):
    d = register(client, role="practitioner", registration_number="NCISM-12345")
    me = client.get("/api/v1/auth/me", headers=H(d)).json()
    assert (
        client.post(f"/api/v1/admin/practitioners/{me['id']}/verify", headers=H(admin)).status_code
        == 200
    )
    return d


# --- auth ------------------------------------------------------------------------------------
def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").json()["database"] is True


def test_register_validation_and_duplicates(client):
    bad = client.post(
        "/api/v1/auth/register",
        json={"email": "x@test.ayurnidaan.in", "password": "short", "full_name": "X"},
    )
    assert bad.status_code == 422
    p = register(client)
    dup = client.post(
        "/api/v1/auth/register", json={"email": p["_email"], "password": PW, "full_name": "Yash"}
    )
    assert dup.status_code == 409
    nodoc = client.post(
        "/api/v1/auth/register",
        json={
            "email": "d@test.ayurnidaan.in",
            "password": PW,
            "full_name": "Dr",
            "role": "practitioner",
        },
    )
    assert nodoc.status_code == 422


def test_login_refresh_and_revocation(client):
    p = register(client)
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": p["_email"], "password": "wrong-password"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "nobody@test.ayurnidaan.in", "password": PW}
        ).status_code
        == 401
    )
    assert (
        client.post("/api/v1/auth/refresh", json={"refresh_token": p["_refresh"]}).status_code
        == 200
    )
    assert client.post("/api/v1/auth/logout-all", headers=H(p)).status_code == 204
    assert (
        client.post("/api/v1/auth/refresh", json={"refresh_token": p["_refresh"]}).status_code
        == 401
    )
    assert client.get("/api/v1/auth/me", headers=H(p)).status_code == 401  # old access token too


def test_tampered_token_rejected(client):
    p = register(client)
    token = H(p)["Authorization"]
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": token[:-2] + "xx"}).status_code
        == 401
    )
    assert client.get("/api/v1/auth/me").status_code == 401


# --- patient flow -----------------------------------------------------------------------------
def test_location_needs_consent_and_derives_desha(client):
    p = register(client)
    loc = {"latitude": 28.3612, "longitude": 75.6031, "state": "Rajasthan"}
    assert client.put("/api/v1/me/location", headers=H(p), json=loc).status_code == 403
    client.post("/api/v1/me/consents", headers=H(p), json={"purpose": "location", "granted": True})
    prof = client.put("/api/v1/me/location", headers=H(p), json=loc).json()
    assert prof["desha"] == "jangala" and prof["location_cell"] == [
        28.4,
        75.6,
    ]  # rounded, not exact
    client.post("/api/v1/me/consents", headers=H(p), json={"purpose": "location", "granted": False})
    assert client.get("/api/v1/me/profile", headers=H(p)).json()["location_cell"] is None


def test_encounter_requires_complete_checklist(client):
    p = register(client)
    r = client.post(
        "/api/v1/encounters", headers=H(p), json={"red_flag_checklist": {"chest_pain": False}}
    )
    assert r.status_code == 422


def test_emergency_encounter_short_circuits(client):
    p = register(client)
    r = client.post(
        "/api/v1/encounters",
        headers=H(p),
        json={"red_flag_checklist": NO_FLAGS | {"breathing": True}},
    ).json()
    assert r["status"] == "emergency" and r["assessment"]["stopped"]


def test_adaptive_answers_and_submit_needs_care_consent(client):
    p, eid = patient_with_case(client, consent=())
    r = client.post(
        f"/api/v1/encounters/{eid}/answers",
        headers=H(p),
        json={"symptoms": {"sputum": True}, "free_text_symptoms": ["chest tightness"]},
    ).json()
    assert r["inputs"]["symptoms"]["chest tightness"] is True
    assert client.post(f"/api/v1/encounters/{eid}/submit", headers=H(p)).status_code == 403
    client.post("/api/v1/me/consents", headers=H(p), json={"purpose": "care", "granted": True})
    assert (
        client.post(f"/api/v1/encounters/{eid}/submit", headers=H(p)).json()["status"]
        == "submitted"
    )
    assert (
        client.post(f"/api/v1/encounters/{eid}/answers", headers=H(p), json={}).status_code == 409
    )


def test_patients_cannot_see_each_other_or_practitioner_routes(client):
    p1, eid = patient_with_case(client)
    p2 = register(client)
    assert client.get(f"/api/v1/encounters/{eid}", headers=H(p2)).status_code == 404
    assert client.get("/api/v1/practitioner/queue", headers=H(p1)).status_code == 403
    assert client.get("/api/v1/admin/audit", headers=H(p1)).status_code == 403


# --- practitioner flow ---------------------------------------------------------------------------
def test_unverified_practitioner_is_blocked(client):
    d = register(client, role="practitioner", registration_number="KA-99")
    assert client.get("/api/v1/practitioner/queue", headers=H(d)).status_code == 403


def test_review_flow_and_triage_ordering(client, doctor):
    p, eid = patient_with_case(client)
    client.post(f"/api/v1/encounters/{eid}/submit", headers=H(p))
    p2 = register(client)
    client.post("/api/v1/me/consents", headers=H(p2), json={"purpose": "care", "granted": True})
    urgent = client.post(
        "/api/v1/encounters",
        headers=H(p2),
        json={"red_flag_checklist": NO_FLAGS, "symptoms": {"chest pain": True, "cough": True}},
    ).json()
    client.post(f"/api/v1/encounters/{urgent['id']}/submit", headers=H(p2))

    queue = client.get("/api/v1/practitioner/queue", headers=H(doctor)).json()
    levels = [q["triage_level"] for q in queue]
    assert levels == sorted(levels, key={"emergency": 0, "urgent": 1, "routine": 2}.get)

    case = client.get(f"/api/v1/practitioner/encounters/{eid}", headers=H(doctor)).json()
    assert case["patient"]["profile"]["sex"] == "female" and case["condition_references"]
    exam = client.post(
        f"/api/v1/practitioner/encounters/{eid}/examination",
        headers=H(doctor),
        json={"examination": {"nadi": "hamsa_kapha", "jihva": "coated_white"}},
    )
    assert exam.status_code == 200 and exam.json()["assessment"]["ama"]["signs"]
    bad = client.post(
        f"/api/v1/practitioner/encounters/{eid}/examination",
        headers=H(doctor),
        json={"examination": {"nadi": "unicorn"}},
    )
    assert bad.status_code == 422

    top = case["encounter"]["assessment"]["differential"][0]["condition_id"]
    rv = client.post(
        f"/api/v1/practitioner/encounters/{eid}/review",
        headers=H(doctor),
        json={"decision": "confirmed", "condition_id": top, "plan": "Pathya, review in 2 weeks"},
    )
    assert rv.json()["status"] == "reviewed"
    mine = client.get(f"/api/v1/encounters/{eid}", headers=H(p)).json()
    assert mine["reviews"][0]["decision"] == "confirmed"
    assert client.get("/api/v1/me/history", headers=H(p)).json()["encounters"][0]["confirmed"]


def test_withdrawn_care_consent_hides_case(client, doctor):
    p, eid = patient_with_case(client)
    client.post(f"/api/v1/encounters/{eid}/submit", headers=H(p))
    client.post("/api/v1/me/consents", headers=H(p), json={"purpose": "care", "granted": False})
    assert (
        client.get(f"/api/v1/practitioner/encounters/{eid}", headers=H(doctor)).status_code == 403
    )


# --- learning loop + insights --------------------------------------------------------------------
def test_learning_only_from_consented_cases(client, doctor, admin):
    status = client.get("/api/v1/admin/learning", headers=H(admin)).json()
    before = status["eligible_cases"]
    # research consent missing -> confirmed case does not count
    p, eid = patient_with_case(client)
    client.post(f"/api/v1/encounters/{eid}/submit", headers=H(p))
    cid = client.get(f"/api/v1/practitioner/encounters/{eid}", headers=H(doctor)).json()[
        "encounter"
    ]["assessment"]["differential"][0]["condition_id"]
    client.post(
        f"/api/v1/practitioner/encounters/{eid}/review",
        headers=H(doctor),
        json={"decision": "confirmed", "condition_id": cid},
    )
    assert client.get("/api/v1/admin/learning", headers=H(admin)).json()["eligible_cases"] == before
    r = client.post("/api/v1/admin/learning/retrain", headers=H(admin)).json()
    assert r["promoted"] is False


def test_retrain_promotes_or_rejects_with_metrics(client, doctor, admin):
    for _ in range(22):
        p, eid = patient_with_case(client, consent=("care", "research"))
        client.post(f"/api/v1/encounters/{eid}/submit", headers=H(p))
        cid = client.get(f"/api/v1/practitioner/encounters/{eid}", headers=H(doctor)).json()[
            "encounter"
        ]["assessment"]["differential"][0]["condition_id"]
        client.post(
            f"/api/v1/practitioner/encounters/{eid}/review",
            headers=H(doctor),
            json={"decision": "confirmed", "condition_id": cid},
        )
    r = client.post("/api/v1/admin/learning/retrain", headers=H(admin)).json()
    assert "metrics" in r and r["metrics"]["holdout_candidate"]["n"] >= 4
    if r["promoted"]:
        assert "+fb" in client.get("/api/v1/meta").json()["engine_version"]


def test_insights_are_k_anonymous(client, doctor):
    ins = client.get("/api/v1/practitioner/insights", headers=H(doctor)).json()
    assert ins["k_anonymity"] == 5
    assert all(
        row["count"] >= 5
        for key in ("ritu_body_system", "desha_dosha", "ritu_condition")
        for row in ins[key]
    )


# --- DPDP rights ---------------------------------------------------------------------------------
def test_export_then_erase(client):
    p, eid = patient_with_case(client)
    data = client.get("/api/v1/me/export", headers=H(p)).json()
    assert data["encounters"][0]["id"] == eid and data["consents"]
    assert client.delete("/api/v1/me", headers=H(p)).status_code == 204
    assert (
        client.post("/api/v1/auth/login", json={"email": p["_email"], "password": PW}).status_code
        == 401
    )


def test_public_reference_endpoints(client):
    assert len(client.get("/api/v1/red-flags").json()) == len(red_flags.CHECKLIST)
    assert client.get("/api/v1/prakriti/questions").json()
    assert client.get("/api/v1/symptoms/search", params={"q": "coug"}).json()[0]["term"] == "cough"
    assert (
        client.get("/api/v1/geo/search", params={"q": "Pilani"}).json()[0]["state"] == "Rajasthan"
    )


def test_production_refuses_dev_secrets():
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        create_app(Settings(environment="production"))
