"""Production-engineering features: caching, rate limiting, DSA, idempotency, pagination,
indexes, observability. Each test exercises the real code path the API uses."""

import itertools
import random
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from ayurnidaan.app import services
from ayurnidaan.app.cache import TTLCache
from ayurnidaan.app.main import create_app
from ayurnidaan.app.pagination import decode_cursor, encode_cursor
from ayurnidaan.app.ratelimit import TokenBucketLimiter, client_ip
from ayurnidaan.clinical import red_flags, topk
from ayurnidaan.clinical.trie import PrefixTrie
from ayurnidaan.config import Settings

NO_FLAGS = {f.code: False for f in red_flags.CHECKLIST}
PW = "correct-horse-battery"


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# --- LRU / TTL cache ---------------------------------------------------------------------------
def test_cache_evicts_least_recently_used():
    c = TTLCache("t", maxsize=2, ttl_seconds=None)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1  # a is now most recent
    c.put("c", 3)  # evicts b, the least recently used
    assert c.get("b") is None and c.get("a") == 1 and c.get("c") == 3
    assert c.evictions == 1


def test_cache_entries_expire():
    clock = FakeClock()
    c = TTLCache("t", maxsize=10, ttl_seconds=60, clock=clock)
    c.put("k", "v")
    clock.t += 59
    assert c.get("k") == "v"
    clock.t += 2
    assert c.get("k") is None and len(c) == 0


def test_get_or_compute_does_not_cache_failures():
    c = TTLCache("t", maxsize=10)
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("upstream down")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            c.get_or_compute("k", boom)
    assert len(calls) == 2  # an outage is retried, not remembered
    assert c.get_or_compute("k", lambda: 42) == 42
    assert c.get_or_compute("k", lambda: 0) == 42


# --- token bucket ------------------------------------------------------------------------------
def test_token_bucket_allows_burst_then_refills():
    clock = FakeClock()
    lim = TokenBucketLimiter({"api": 60}, clock=clock)  # 1 token per second
    assert all(lim.check("ip", "api").allowed for _ in range(60))
    denied = lim.check("ip", "api")
    assert not denied.allowed and 0 < denied.retry_after <= 1
    clock.t += 1.0
    assert lim.check("ip", "api").allowed
    assert not lim.check("ip", "api").allowed
    assert lim.check("other-ip", "api").allowed  # per client


def test_token_bucket_memory_is_bounded():
    lim = TokenBucketLimiter({"api": 5}, max_clients=100)
    for i in range(1000):
        lim.check(f"10.0.{i // 256}.{i % 256}", "api")
    assert len(lim) == 100


def test_client_ip_ignores_spoofed_forwarded_for():
    # one proxy (nginx) appends the peer it saw; the client controls everything left of it
    xff = "6.6.6.6, 203.0.113.9"
    assert client_ip("172.18.0.5", xff, trusted_hops=1) == "203.0.113.9"
    assert client_ip("172.18.0.5", xff, trusted_hops=0) == "172.18.0.5"  # exposed directly
    assert client_ip("172.18.0.5", None, trusted_hops=1) == "172.18.0.5"


# --- trie --------------------------------------------------------------------------------------
def test_trie_completes_by_frequency_and_word_start():
    t = PrefixTrie(k=5)
    for phrase, freq in [("joint pain", 30), ("pain", 50), ("painful urination", 10), ("pallor", 5)]:
        t.insert(phrase, phrase, freq)
    t.build()
    assert [v for v, _ in t.complete("pa")] == [
        "pain",
        "painful urination",
        "pallor",
        "joint pain",  # word-start match ranks after whole-phrase matches
    ]
    assert [v for v, _ in t.complete("jo")] == ["joint pain"]
    assert t.complete("xyz") == []


def test_trie_dedupes_aliases_and_bounds_k():
    t = PrefixTrie(k=3)
    t.insert("loose motions", "diarrhea", 40)
    t.insert("loose stools", "diarrhea", 40)
    for i in range(10):
        t.insert(f"lo{i}", f"term{i}", i)
    t.build()
    out = [v for v, _ in t.complete("lo", limit=10)]
    assert out[0] == "diarrhea" and out.count("diarrhea") == 1 and len(out) == 3


# --- top-k -------------------------------------------------------------------------------------
@pytest.mark.parametrize("seed", range(5))
def test_topk_descending_matches_full_sort(seed):
    rng = np.random.default_rng(seed)
    scores = rng.integers(0, 50, size=500).astype(float)  # many ties
    got = list(topk.descending(scores, expect=10))
    assert sorted(got) == list(range(500))  # every index exactly once
    assert all(scores[a] >= scores[b] for a, b in itertools.pairwise(got))


# --- cursors -----------------------------------------------------------------------------------
def test_cursor_round_trip_and_tamper():
    from datetime import datetime

    from fastapi import HTTPException

    when = datetime(2026, 10, 1, 9, 30)
    c = encode_cursor(1, when, "abc")
    assert decode_cursor(c, (int, datetime, str)) == (1, when, "abc")
    with pytest.raises(HTTPException):
        decode_cursor("not-a-cursor", (int, datetime, str))


# --- API ---------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app_client(synthetic_settings, pipeline_run, tmp_path_factory):
    db = tmp_path_factory.mktemp("prod") / "app.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{db.as_posix()}",
        knowledge_dir=synthetic_settings.knowledge_dir,
        bootstrap_admin_email="admin-prod@test.ayurnidaan.in",
    )
    with TestClient(create_app(settings)) as c:
        yield c


def _register(c, role="patient", email=None, **extra):
    email = email or f"{role}-{uuid.uuid4().hex[:8]}@test.ayurnidaan.in"
    r = c.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PW, "full_name": "Test user", "role": role, **extra},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _patient(c):
    h = _register(c)
    c.put("/api/v1/me/profile", headers=h, json={"date_of_birth": "1990-01-01", "sex": "male"})
    c.post("/api/v1/me/consents", headers=h, json={"purpose": "care", "granted": True})
    return h


def _case(c, h, **extra_headers):
    return c.post(
        "/api/v1/encounters",
        headers={**h, **extra_headers},
        json={"red_flag_checklist": NO_FLAGS, "symptoms": {"cough": True}},
    )


@pytest.fixture(scope="module")
def doctor(app_client):
    admin = _register(app_client, email="admin-prod@test.ayurnidaan.in")
    d = _register(app_client, role="practitioner", registration_number="NCISM-1")
    me = app_client.get("/api/v1/auth/me", headers=d).json()
    app_client.post(f"/api/v1/admin/practitioners/{me['id']}/verify", headers=admin)
    return d


def test_idempotent_create_never_duplicates(app_client):
    h = _patient(app_client)
    key = {"Idempotency-Key": uuid.uuid4().hex}
    first = _case(app_client, h, **key)
    retry = _case(app_client, h, **key)
    assert first.status_code == retry.status_code == 201
    assert retry.json()["id"] == first.json()["id"]
    assert retry.headers["idempotent-replayed"] == "true"
    assert len(app_client.get("/api/v1/encounters", headers=h).json()) == 1

    other_body = app_client.post(
        "/api/v1/encounters",
        headers={**h, **key},
        json={"red_flag_checklist": NO_FLAGS, "symptoms": {"fever": True}},
    )
    assert other_body.status_code == 422  # same key, different request: a client bug
    assert _case(app_client, h, **{"Idempotency-Key": "bad key!"}).status_code == 400
    # without the header nothing changes: two calls, two encounters
    _case(app_client, h)
    _case(app_client, h)
    assert len(app_client.get("/api/v1/encounters", headers=h).json()) == 3


def test_idempotency_keys_are_per_user(app_client):
    key = {"Idempotency-Key": uuid.uuid4().hex}
    a, b = _patient(app_client), _patient(app_client)
    ea, eb = _case(app_client, a, **key).json(), _case(app_client, b, **key).json()
    assert ea["id"] != eb["id"]  # B can never receive A's stored response


def test_idempotent_review_records_one_label(app_client, doctor):
    h = _patient(app_client)
    eid = _case(app_client, h).json()["id"]
    app_client.post(f"/api/v1/encounters/{eid}/submit", headers=h)
    case = app_client.get(f"/api/v1/practitioner/encounters/{eid}", headers=doctor).json()
    cid = case["encounter"]["assessment"]["differential"][0]["condition_id"]
    key = {"Idempotency-Key": uuid.uuid4().hex}
    body = {"decision": "confirmed", "condition_id": cid}
    url = f"/api/v1/practitioner/encounters/{eid}/review"
    r1 = app_client.post(url, headers={**doctor, **key}, json=body)
    r2 = app_client.post(url, headers={**doctor, **key}, json=body)
    assert r1.status_code == r2.status_code == 200
    assert len(r2.json()["reviews"]) == 1
    assert len(app_client.get(f"/api/v1/encounters/{eid}", headers=h).json()["reviews"]) == 1


def test_queue_pages_cover_everything_once_in_triage_order(app_client, doctor):
    for _ in range(7):
        h = _patient(app_client)
        eid = _case(app_client, h).json()["id"]
        app_client.post(f"/api/v1/encounters/{eid}/submit", headers=h)
    full = app_client.get("/api/v1/practitioner/queue", headers=doctor).json()
    seen, cursor = [], None
    while True:
        params = {"limit": 3} | ({"cursor": cursor} if cursor else {})
        r = app_client.get("/api/v1/practitioner/queue", headers=doctor, params=params)
        assert r.status_code == 200 and len(r.json()) <= 3
        seen += [row["id"] for row in r.json()]
        cursor = r.headers.get("x-next-cursor")
        if not cursor:
            break
    assert seen == [row["id"] for row in full] and len(set(seen)) == len(seen) >= 7
    bad = app_client.get("/api/v1/practitioner/queue", headers=doctor, params={"cursor": "x"})
    assert bad.status_code == 400


def test_patient_list_pages_newest_first(app_client):
    h = _patient(app_client)
    ids = [_case(app_client, h).json()["id"] for _ in range(5)]
    first = app_client.get("/api/v1/encounters", headers=h, params={"limit": 2})
    second = app_client.get(
        "/api/v1/encounters",
        headers=h,
        params={"limit": 10, "cursor": first.headers["x-next-cursor"]},
    )
    got = [e["id"] for e in first.json() + second.json()]
    assert sorted(got) == sorted(ids) and "x-next-cursor" not in second.headers


def test_queue_has_no_n_plus_1(app_client, doctor):
    """The number of SQL statements for one queue page must not grow with its size."""
    engine = app_client.app.state.db.engine
    statements = []

    def count(*_):
        statements.append(1)

    def queries_for(limit):
        statements.clear()
        event.listen(engine, "before_cursor_execute", count)
        try:
            n = len(
                app_client.get(
                    "/api/v1/practitioner/queue", headers=doctor, params={"limit": limit}
                ).json()
            )
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return n, len(statements)

    small, q_small = queries_for(1)
    large, q_large = queries_for(50)
    assert large > small and q_large == q_small


def test_reference_data_is_http_cacheable_and_per_user_data_is_not(app_client):
    r = app_client.get("/api/v1/symptoms")
    assert r.headers["cache-control"] == "public, max-age=300" and r.headers["etag"]
    again = app_client.get("/api/v1/symptoms", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304 and not again.content
    h = _patient(app_client)
    assert app_client.get("/api/v1/me/profile", headers=h).headers["cache-control"] == "no-store"


def test_symptom_and_geo_search_are_memoised(app_client, monkeypatch):
    state = app_client.app.state
    state.search_cache.clear()
    a = app_client.get("/api/v1/symptoms/search", params={"q": "cou"}).json()
    b = app_client.get("/api/v1/symptoms/search", params={"q": "COU "}).json()
    assert a == b and state.search_cache.hits >= 1

    calls = []

    def fake(url, timeout=20):
        calls.append(url)
        return {"results": [{"name": "Pilani", "latitude": 28.36, "longitude": 75.6}]}

    monkeypatch.setattr(services, "_http_json", fake)
    state.geo_cache.clear()
    for _ in range(3):
        assert app_client.get("/api/v1/geo/search", params={"q": "Pilani"}).status_code == 200
    assert len(calls) == 1  # one outbound call for three identical searches


def test_health_endpoints(app_client):
    assert app_client.get("/healthz").json()["status"] == "ok"
    ready = app_client.get("/readyz")
    assert ready.status_code == 200 and ready.json()["ready"] and ready.json()["database"]


def test_request_id_is_echoed_and_sanitised(app_client):
    assert app_client.get("/healthz", headers={"X-Request-ID": "abc-123"}).headers[
        "x-request-id"
    ] == ("abc-123")
    injected = app_client.get("/healthz", headers={"X-Request-ID": 'x" level=CRITICAL'})
    assert injected.headers["x-request-id"] != 'x" level=CRITICAL'


def test_metrics_expose_route_templates(app_client):
    h = _patient(app_client)
    eid = _case(app_client, h).json()["id"]
    app_client.get(f"/api/v1/encounters/{eid}", headers=h)
    body = app_client.get("/metrics").text
    assert 'route="/api/v1/encounters/{encounter_id}"' in body  # template, not the raw id
    assert eid not in body
    assert "ayur_http_request_duration_seconds_bucket" in body
    assert "ayur_engine_assessment_seconds_count" in body


def test_metrics_token_and_rate_limit_behind_proxy(synthetic_settings, pipeline_run, tmp_path):
    settings = Settings(
        environment="development",
        database_url=f"sqlite:///{(tmp_path / 'm.db').as_posix()}",
        knowledge_dir=synthetic_settings.knowledge_dir,
        metrics_token="s3cret-token",
        rate_limit_per_minute=2,
        trusted_proxy_hops=1,
    )
    with TestClient(create_app(settings)) as c:
        assert c.get("/metrics").status_code == 401
        ok = c.get("/metrics", headers={"Authorization": "Bearer s3cret-token"})
        assert ok.status_code == 200
        # A client rotating fake X-Forwarded-For values is still one client to us.
        codes = [
            c.get(
                "/api/v1/red-flags",
                headers={"X-Forwarded-For": f"10.9.9.{random.randint(1, 250)}, 198.51.100.7"},
            ).status_code
            for _ in range(3)
        ]
        assert codes == [200, 200, 429]
        limited = c.get("/api/v1/red-flags", headers={"X-Forwarded-For": "198.51.100.7"})
        assert limited.headers["retry-after"] and limited.headers["ratelimit-remaining"] == "0"
        assert c.get("/healthz").status_code == 200  # probes are never rate limited


# --- indexes: the planner really uses them ---------------------------------------------------
def test_sqlite_plans_use_the_composite_indexes(app_client):
    from ayurnidaan.app.routers.practitioner import queue_query

    engine = app_client.app.state.db.engine
    with engine.connect() as conn:
        sql = queue_query("u1", "submitted", None, 50).compile(
            engine, compile_kwargs={"literal_binds": True}
        )
        plan = " ".join(r[-1] for r in conn.execute(text(f"EXPLAIN QUERY PLAN {sql}")))
        assert "ix_encounters_queue" in plan and "TEMP B-TREE" not in plan, plan
        plan = " ".join(
            r[-1]
            for r in conn.execute(
                text(
                    "EXPLAIN QUERY PLAN SELECT id FROM encounters WHERE patient_id = 'p' "
                    "ORDER BY created_at DESC, id DESC LIMIT 51"
                )
            )
        )
        assert "ix_encounters_patient_created" in plan and "TEMP B-TREE" not in plan, plan
