"""Public reference endpoints the intake UI needs before / without login."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response

from ... import __version__
from ...clinical import pariksha, red_flags
from ..deps import AppSettings, Clinical, CurrentUser
from ..pagination import cached_json
from ..services import geocode

router = APIRouter(tags=["knowledge"])

# Reference data below is identical for every caller and changes only with a deploy
# (code version) or a new knowledge pack / learned model, so it is HTTP-cacheable:
# ETag + short max-age (pagination.cached_json). Per-user data stays no-store.


@router.get("/meta")
def meta(request: Request, clinical: Clinical) -> Response:
    m = clinical.pack.manifest
    body = {
        "engine_version": clinical.engine.version,
        "knowledge_pack": m["content_id"],
        "built_at": m["built_at"],
        "counts": m["counts"],
        "metrics": m.get("metrics", {}),
        "benchmark": m.get("benchmark"),
    }
    return cached_json(request, body, clinical.engine.version, max_age=60)


@router.get("/red-flags")
def red_flag_checklist(request: Request) -> Response:
    body = [{"code": f.code, "question": f.question} for f in red_flags.CHECKLIST]
    return cached_json(request, body, __version__)


@router.get("/prakriti/questions")
def prakriti_questions(request: Request, clinical: Clinical) -> Response:
    body = [
        {"id": q["id"], "question": q["question"], "options": [o["value"] for o in q["options"]]}
        for q in clinical.pack.prakriti["questions"]
    ]
    return cached_json(request, body, clinical.pack.version)


@router.get("/intake-options")
def intake_options(request: Request) -> Response:
    body = {
        "aggravating": list(pariksha.AGGRAVATING),
        "relieving": list(pariksha.RELIEVING),
        "agni": list(pariksha.AGNI),
        "examination": {k: list(v) for k, v in pariksha.EXAMINATION.items()},
    }
    return cached_json(request, body, __version__)


@router.get("/symptoms/search")
def symptom_search(
    request: Request,
    clinical: Clinical,
    q: str = Query(min_length=1, max_length=80),
    limit: int = Query(8, ge=1, le=20),
) -> list[dict]:
    """Autocomplete. Results depend only on (knowledge pack, query, limit), so they are
    memoised in an LRU cache keyed by all three: a new pack can never serve stale hits."""
    key = (clinical.pack.version, q.casefold().strip(), limit)
    cache = request.app.state.search_cache
    return cache.get_or_compute(key, lambda: clinical.engine.search.search(q, limit=limit))


@router.get("/symptoms")
def symptoms(request: Request, clinical: Clinical) -> Response:
    body = [
        {"term": s["term"], "cluster": s["cluster"], "doc_freq": s["doc_freq"]}
        for s in clinical.pack.symptoms
    ]
    return cached_json(request, body, clinical.pack.version)


@router.get("/conditions/{condition_id}")
def condition(condition_id: str, user: CurrentUser, clinical: Clinical) -> dict:
    c = clinical.condition(condition_id)  # O(1) dict lookup, not a scan of 1,446 rows
    if c is None:
        raise HTTPException(404, "condition not found")
    public = {
        k: c[k]
        for k in (
            "id",
            "name",
            "modern_equivalent",
            "body_system",
            "dosha",
            "prognosis",
            "namc",
            "symptoms",
            "patient_guidance",
            "prevalence",
        )
    }
    if user.role in ("practitioner", "admin"):
        public["practitioner_reference"] = c["practitioner_reference"]
        public["literature"] = c.get("literature")
        public["papers"] = clinical.pack.evidence.get(c.get("evidence_key"), {}).get("papers", [])
    return public


@router.get("/geo/search")
def geo_search(
    request: Request, settings: AppSettings, q: str = Query(min_length=2, max_length=80)
) -> list[dict]:
    """Place search, proxied to Open-Meteo. Each miss is an outbound HTTPS call, and place
    names do not change, so results are cached for a day (failures are not cached)."""
    key = (settings.geocode_country, q.casefold().strip())
    try:
        return request.app.state.geo_cache.get_or_compute(key, lambda: geocode(settings, q))
    except Exception as exc:
        raise HTTPException(503, "place search unavailable") from exc
