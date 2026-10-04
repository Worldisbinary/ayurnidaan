"""Public reference endpoints the intake UI needs before / without login."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...clinical import pariksha, red_flags
from ..deps import AppSettings, Clinical, CurrentUser
from ..services import geocode

router = APIRouter(tags=["knowledge"])


@router.get("/meta")
def meta(clinical: Clinical) -> dict:
    m = clinical.pack.manifest
    return {
        "engine_version": clinical.engine.version,
        "knowledge_pack": m["content_id"],
        "built_at": m["built_at"],
        "counts": m["counts"],
        "metrics": m.get("metrics", {}),
        "benchmark": m.get("benchmark"),
    }


@router.get("/red-flags")
def red_flag_checklist() -> list[dict]:
    return [{"code": f.code, "question": f.question} for f in red_flags.CHECKLIST]


@router.get("/prakriti/questions")
def prakriti_questions(clinical: Clinical) -> list[dict]:
    return [
        {"id": q["id"], "question": q["question"], "options": [o["value"] for o in q["options"]]}
        for q in clinical.pack.prakriti["questions"]
    ]


@router.get("/intake-options")
def intake_options() -> dict:
    return {
        "aggravating": list(pariksha.AGGRAVATING),
        "relieving": list(pariksha.RELIEVING),
        "agni": list(pariksha.AGNI),
        "examination": {k: list(v) for k, v in pariksha.EXAMINATION.items()},
    }


@router.get("/symptoms/search")
def symptom_search(
    clinical: Clinical, q: str = Query(min_length=1, max_length=80), limit: int = 8
) -> list[dict]:
    return clinical.engine.search.search(q, limit=min(limit, 20))


@router.get("/symptoms")
def symptoms(clinical: Clinical) -> list[dict]:
    return [
        {"term": s["term"], "cluster": s["cluster"], "doc_freq": s["doc_freq"]}
        for s in clinical.pack.symptoms
    ]


@router.get("/conditions/{condition_id}")
def condition(condition_id: str, user: CurrentUser, clinical: Clinical) -> dict:
    c = next((c for c in clinical.pack.conditions if c["id"] == condition_id), None)
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
def geo_search(settings: AppSettings, q: str = Query(min_length=2, max_length=80)) -> list[dict]:
    try:
        return geocode(settings, q)
    except Exception as exc:
        raise HTTPException(503, "place search unavailable") from exc
