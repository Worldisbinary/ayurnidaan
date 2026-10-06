import json
import re
import uuid
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from ayurnidaan.app import digilocker as dl
from ayurnidaan.app.main import create_app
from ayurnidaan.clinical import ayurveda as A
from ayurnidaan.clinical import modules as M
from ayurnidaan.clinical import red_flags
from ayurnidaan.clinical.kala_desha import upcoming_ritus
from ayurnidaan.config import PROJECT_ROOT, Settings

NO_FLAGS = {f.code: False for f in red_flags.CHECKLIST}
PW = "correct-horse-battery"
REAL_SYMPTOMS = PROJECT_ROOT / "knowledge_pack" / "symptoms.json"


# --- rule tables --------------------------------------------------------------------------
@pytest.mark.skipif(not REAL_SYMPTOMS.exists(), reason="committed knowledge pack not present")
def test_every_rule_sign_is_a_canonical_symptom():
    vocab = {s["term"] for s in json.loads(REAL_SYMPTOMS.read_text(encoding="utf-8"))["terms"]}
    missing = [
        (n, s)
        for tbl, keys in (
            (A.SUBDOSHAS, ["signs"]),
            (A.DHATUS, ["kshaya", "vriddhi"]),
            (A.SROTAS, ["signs"]),
        )
        for n, row in tbl.items()
        for k in keys
        for s in row[k]
        if s not in vocab
    ]
    assert missing == []


def test_derive_maps_symptoms_to_subdoshas_dhatus_srotas():
    d = A.derive(["constipation", "gas", "joint pain", "stiffness", "anxiety"], bmi=17.0)
    sub = {s["name"]: s for s in d.subdoshas}
    assert sub["apana"]["dosha"] == "vata" and sub["shleshaka"]["dosha"] == "kapha"
    dh = {x["name"]: x["state"] for x in d.dhatus}
    assert dh["mamsa"] == "kshaya" and dh["shukra"] == "normal"
    assert {x["name"] for x in d.srotas if x["involved"]} >= {"purishavaha", "manovaha"}


@pytest.mark.parametrize(
    ("age", "stage"), [(10, "bala"), (29, "bala"), (30, "madhya"), (60, "jirna")]
)
def test_vaya_boundaries(age, stage):
    assert A.vaya(age)["stage"] == stage


@pytest.mark.parametrize(
    ("hour", "dosha"), [(7, "kapha"), (12, "pitta"), (15, "vata"), (23, "pitta"), (3, "vata")]
)
def test_dosha_clock(hour, dosha):
    assert A.dosha_clock(hour)["current"] == dosha


def test_ritu_forecast_orders_upcoming_changes():
    f = upcoming_ritus(date(2026, 3, 1), 2)
    assert [x["ritu"] for x in f] == ["vasanta", "grishma"]
    assert f[0]["aggravates"] == ["kapha"] and f[0]["days_away"] == 14


# --- modules --------------------------------------------------------------------------------
def test_ojas_score_and_levels():
    best = M.OJAS.score(
        {
            "energy": "steady",
            "recovery": "quick",
            "infections": "rare",
            "sleep": "refreshing",
            "stress": "calm",
            "vyayamashakti": "high",
        }
    )
    worst = M.OJAS.score(
        {
            "energy": "exhausted",
            "recovery": "slow",
            "infections": "frequent",
            "sleep": "light",
            "stress": "overwhelmed",
            "vyayamashakti": "low",
        }
    )
    assert best["ojas_score"] == 100 and best["bala"] == "pravara"
    assert worst["bala"] == "avara"


@pytest.mark.parametrize(
    ("h", "w", "cat"),
    [(170, 50, "underweight"), (170, 63, "normal"), (170, 70, "overweight"), (170, 80, "obese")],
)
def test_bmi_uses_asian_cutoffs(h, w, cat):
    assert M.DASHAVIDHA.score({"height_cm": h, "weight_kg": w})["pramana"] == cat


def test_module_validation_rejects_bad_answers():
    with pytest.raises(ValueError):
        M.OJAS.score({"energy": "invented"})
    with pytest.raises(ValueError):
        M.DASHAVIDHA.score({"height_cm": 900})
    with pytest.raises(ValueError):
        M.OJAS.score({})


def test_manas_shares_sum_to_one():
    r = M.MANAS.score({"criticism": "s", "drive": "r", "food": "t", "work": "s"})
    assert (
        sum(r["guna_shares"].values()) == pytest.approx(1, abs=0.01) and r["dominant"] == "sattva"
    )


def test_viruddha_and_taste_analysis():
    a = M.analyse_meals(
        {"breakfast": ["milk", "fish"], "lunch": ["rice", "dal"], "dinner": ["curd"]}
    )
    msgs = " ".join(f["message"] for f in a["viruddha"])
    assert "fish" in msgs and "Curd at night" in msgs
    clean = M.analyse_meals({"lunch": ["curd", "rice"]})  # curd at lunch is fine
    assert clean["viruddha"] == []
    assert a["tastes"]["sweet"] >= 2 and "pungent" in a["missing_tastes"]


def test_dinacharya_score():
    assert M.dinacharya_score({k: True for k in M.DINACHARYA}) == 100
    assert M.dinacharya_score({"woke_before_6": True, "unknown": True}) == 15


# --- DigiLocker parsing ---------------------------------------------------------------------
def test_parse_user_details_and_eaadhaar():
    ident = dl.parse_user_details({"name": "Asha Sharma", "dob": "12031984", "gender": "F"})
    assert ident.dob == date(1984, 3, 12) and ident.sex == "female"
    xml = (
        '<Certificate><CertificateData><KycRes><UidData><Poi name="Asha" dob="12-03-1984" gender="F"/>'
        '<Poa dist="Jhunjhunu" state="Rajasthan" pc="333031"/></UidData></KycRes></CertificateData></Certificate>'
    )
    assert dl.parse_eaadhaar_address(xml) == ("Rajasthan", "Jhunjhunu")
    assert dl.parse_eaadhaar_address("not xml") == (None, None)


def test_names_match_and_return_allowlist():
    assert dl.names_match("ASHA KUMARI SHARMA", "Asha Sharma") is True
    assert dl.names_match("Ravi Menon", "Asha Sharma") is False
    s = Settings(cors_origins=["https://ayurnidaan.vercel.app"])
    assert dl.allowed_return(s, "https://ayurnidaan.vercel.app/profile")
    assert dl.allowed_return(s, "ayurnidaan://profile")
    assert not dl.allowed_return(s, "https://ayurnidaan.vercel.app.evil.com/x")
    assert not dl.allowed_return(s, "https://evil.com/")


def test_digilocker_mode_defaults():
    assert Settings(environment="development").digilocker_effective_mode == "sandbox"
    assert Settings(environment="production").digilocker_effective_mode == "disabled"
    with pytest.raises(RuntimeError):
        dl.provider(Settings(digilocker_mode="production"))  # no client credentials


# --- API ------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client(synthetic_settings, pipeline_run, tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "ayur.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{db.as_posix()}",
        knowledge_dir=synthetic_settings.knowledge_dir,
        cors_origins=["http://localhost:8081"],
        bootstrap_admin_email="admin@test.ayurnidaan.in",
    )
    with TestClient(create_app(settings)) as c:
        yield c


def register(c, role="patient", **extra) -> dict:
    email = f"{role}-{uuid.uuid4().hex[:8]}@test.ayurnidaan.in"
    r = c.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PW, "full_name": "Meera Iyer", "role": role, **extra},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_digilocker_sandbox_flow(client):
    h = register(client)
    assert (
        client.post(
            "/api/v1/me/digilocker/start", headers=h, json={"return_to": "https://evil.com/"}
        ).status_code
        == 422
    )
    start = client.post(
        "/api/v1/me/digilocker/start",
        headers=h,
        json={"return_to": "http://localhost:8081/profile"},
    ).json()
    q = parse_qs(urlparse(start["authorize_url"]).query)
    page = client.get(
        "/api/v1/digilocker/sandbox/authorize",
        params={"state": q["state"][0], "redirect_uri": q["redirect_uri"][0]},
    )
    allow = re.search(r'class="allow" href="([^"]+)"', page.text).group(1).replace("&amp;", "&")
    path = urlparse(allow).path + "?" + urlparse(allow).query
    cb = client.get(path, follow_redirects=False)
    assert cb.status_code == 303 and cb.headers["location"].endswith("digilocker=ok")
    assert client.get(path, follow_redirects=False).status_code == 400  # state is single-use
    prof = client.get("/api/v1/me/profile", headers=h).json()
    assert prof["date_of_birth"] == "1990-05-21" and prof["district"] == "Jhunjhunu"
    assert client.get("/api/v1/me/consents", headers=h).json()["consents"]["identity"] is True


def test_digilocker_sandbox_page_escapes_state(client):
    start = client.post(
        "/api/v1/me/digilocker/start",
        headers=register(client),
        json={"return_to": "http://localhost:8081/profile"},
    ).json()
    redirect_uri = parse_qs(urlparse(start["authorize_url"]).query)["redirect_uri"][0]
    evil = '"><script>alert(1)</script>'
    page = client.get(
        "/api/v1/digilocker/sandbox/authorize", params={"state": evil, "redirect_uri": redirect_uri}
    )
    assert page.status_code == 200
    assert "<script>" not in page.text and evil not in page.text
    assert "script-src" not in page.headers["content-security-policy"]  # no scripts at all
    assert page.headers["content-security-policy"].startswith("default-src 'none'")


def test_digilocker_deny(client):
    h = register(client)
    start = client.post(
        "/api/v1/me/digilocker/start",
        headers=h,
        json={"return_to": "http://localhost:8081/profile"},
    ).json()
    state = parse_qs(urlparse(start["authorize_url"]).query)["state"][0]
    cb = client.get(
        "/api/v1/digilocker/callback",
        params={"state": state, "error": "access_denied"},
        follow_redirects=False,
    )
    assert cb.headers["location"].endswith("digilocker=denied")
    assert client.get("/api/v1/me/profile", headers=h).json()["date_of_birth"] is None


def test_modules_feed_profile_and_checkups(client):
    h = register(client)
    client.put("/api/v1/me/profile", headers=h, json={"date_of_birth": "1990-01-01", "sex": "male"})
    mods = {m["id"] for m in client.get("/api/v1/questionnaires", headers=h).json()}
    assert "artava" not in mods and "prakriti_full" in mods  # artava only for women
    assert (
        client.post(
            "/api/v1/me/modules/artava", headers=h, json={"answers": {"flow": "heavy"}}
        ).status_code
        == 404
    )
    client.post(
        "/api/v1/me/modules/agni_mala",
        headers=h,
        json={"answers": {"agni": "slow", "stool": "sticky_heavy", "urine": "normal"}},
    )
    client.post(
        "/api/v1/me/modules/dashavidha",
        headers=h,
        json={"answers": {"height_cm": 170, "weight_kg": 80}},
    )
    enc = client.post(
        "/api/v1/encounters",
        headers=h,
        json={"red_flag_checklist": NO_FLAGS, "symptoms": {"cough": True, "wheezing": True}},
    ).json()
    assert enc["inputs"]["reported_examination"] == {"mala": "sticky_heavy"}
    assert enc["inputs"]["bmi"] == 27.7 and enc["inputs"]["agni"] == "slow_heavy_after_meals"
    assert "ayurveda" in enc["assessment"] and enc["assessment"]["vaya"]["stage"] == "madhya"
    prof = client.get("/api/v1/me/ayurveda", headers=h).json()
    assert prof["dashavidha"]["pramana"] == "obese"
    meda = next(x for x in prof["ayurveda"]["dhatus"] if x["name"] == "meda")
    assert meda["state"] == "vriddhi"
    assert 0 < prof["completeness"]["score"] < 100


def test_daily_log_validation_and_trends(client):
    h = register(client)
    today = date.today()
    ok = client.put(
        f"/api/v1/me/daily/{today}",
        headers=h,
        json={"dinacharya": {"woke_before_6": True}, "meals": {"breakfast": ["milk", "banana"]}},
    )
    assert ok.status_code == 200 and ok.json()["analysis"]["viruddha"]
    again = client.put(
        f"/api/v1/me/daily/{today}", headers=h, json={"dinacharya": {"slept_7_8": True}}
    )
    assert again.json()["score"] == 15  # upsert replaces the day
    assert (
        client.put(f"/api/v1/me/daily/{today + timedelta(days=1)}", headers=h, json={}).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/v1/me/daily/{today}", headers=h, json={"meals": {"lunch": ["unicorn"]}}
        ).status_code
        == 422
    )
    assert len(client.get("/api/v1/me/daily", headers=h).json()) == 1
    assert client.get("/api/v1/me/trends", headers=h).json()["dinacharya"][0]["score"] == 15


def test_practitioner_sees_ayurveda_profile(client):
    a = client.post(
        "/api/v1/auth/register",
        json={"email": "admin@test.ayurnidaan.in", "password": PW, "full_name": "Admin"},
    ).json()
    ah = {"Authorization": f"Bearer {a['access_token']}"}
    d = register(client, role="practitioner", registration_number="KA-1")
    did = client.get("/api/v1/auth/me", headers=d).json()["id"]
    client.post(f"/api/v1/admin/practitioners/{did}/verify", headers=ah)
    p = register(client)
    client.post("/api/v1/me/consents", headers=p, json={"purpose": "care", "granted": True})
    enc = client.post(
        "/api/v1/encounters",
        headers=p,
        json={"red_flag_checklist": NO_FLAGS, "symptoms": {"itching": True}},
    ).json()
    client.post(f"/api/v1/encounters/{enc['id']}/submit", headers=p)
    case = client.get(f"/api/v1/practitioner/encounters/{enc['id']}", headers=d).json()
    prof = case["ayurveda_profile"]
    assert "vaya" in prof and "completeness" in prof
    assert any(x["name"] == "rakta" for x in prof["ayurveda"]["dhatus"])
