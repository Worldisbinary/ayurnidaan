"""Practitioner workspace: triaged queue, full case view, pariksha, diagnosis review."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import or_, select, tuple_
from sqlalchemy.orm import selectinload

from ..ayurveda_profile import build as build_ayurveda
from ..deps import DB, Clinical, Practitioner
from ..idempotency import Idempotent
from ..models import Encounter, Review, User
from ..pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page
from ..schemas import ExaminationIn, ReviewIn
from ..services import audit, current_consents, patient_history, population_insights
from .encounters import encounter_out, run_assessment
from .me import profile_out

router = APIRouter(prefix="/practitioner", tags=["practitioner"])


def queue_query(user_id: str, status: str, after: tuple | None, limit: int):
    """Emergency and urgent cases first, then oldest first; keyset-paginated.

    ORDER BY (triage_rank, created_at, id) is exactly the ix_encounters_queue index order
    after its leading ``status`` column, so the database reads the first ``limit + 1``
    index entries and stops. ``scripts/explain_queries.py`` checks this plan.
    """
    q = select(Encounter).where(
        Encounter.status == status,
        or_(Encounter.practitioner_id.is_(None), Encounter.practitioner_id == user_id),
    )
    if after is not None:
        q = q.where(tuple_(Encounter.triage_rank, Encounter.created_at, Encounter.id) > after)
    return q.order_by(Encounter.triage_rank, Encounter.created_at, Encounter.id).limit(limit + 1)


def _visible(db, user: User, encounter_id: str) -> Encounter:
    e = db.get(Encounter, encounter_id)
    if (
        e is None
        or e.status not in ("submitted", "reviewed")
        or (e.practitioner_id not in (None, user.id))
    ):
        raise HTTPException(404, "encounter not found")
    if not current_consents(db, e.patient_id).get("care"):
        raise HTTPException(403, "patient has withdrawn consent for care sharing")
    return e


@router.get("/queue")
def queue(
    user: Practitioner,
    db: DB,
    response: Response,
    status: str = "submitted",
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
) -> list[dict]:
    """Triaged queue, one page at a time. More pages: pass back ``X-Next-Cursor``."""
    after = decode_cursor(cursor, (int, datetime, str)) if cursor else None
    rows = db.scalars(
        queue_query(user.id, status, after, limit)
        # Patients and their profiles in 2 extra queries for the whole page, instead of
        # 2 per row (the N+1 query problem).
        .options(selectinload(Encounter.patient).selectinload(User.profile))
    ).all()
    rows = page(list(rows), limit, lambda e: (e.triage_rank, e.created_at, e.id), response)
    out = []
    for e in rows:
        top = ((e.assessment or {}).get("differential") or [{}])[0]
        patient = e.patient
        p = patient.profile if patient else None
        out.append(
            {
                "id": e.id,
                "created_at": e.created_at.isoformat(),
                "triage_level": e.triage_level,
                "chief_complaint": e.chief_complaint,
                "assigned_to_me": e.practitioner_id == user.id,
                "patient": {
                    "name": patient.full_name if patient else None,
                    "sex": p.sex if p else None,
                    "age": (e.inputs or {}).get("age"),
                    "desha": p.desha if p else None,
                },
                "top_condition": top.get("name"),
                "top_likelihood": top.get("likelihood"),
                "vikriti": ((e.assessment or {}).get("vikriti") or {}).get("dominant"),
                "ritu": e.ritu,
                "n_symptoms": len((e.inputs or {}).get("symptoms", {})),
            }
        )
    return out


@router.post("/encounters/{encounter_id}/claim")
def claim(encounter_id: str, user: Practitioner, db: DB) -> dict:
    e = _visible(db, user, encounter_id)
    e.practitioner_id = user.id
    audit(db, user.id, "encounter.claim", "encounter", e.id)
    db.commit()
    return {"id": e.id, "practitioner_id": user.id}


@router.get("/encounters/{encounter_id}")
def case_view(encounter_id: str, user: Practitioner, db: DB, clinical: Clinical) -> dict:
    """Everything needed to review: encounter, patient profile and history, and for each
    candidate condition the practitioner reference (treatment principles, herbs, tests)
    and Ayurveda literature."""
    e = _visible(db, user, encounter_id)
    patient = db.get(User, e.patient_id)
    refs = {}
    for d in (e.assessment or {}).get("differential", [])[:8]:
        c = clinical.condition(d["condition_id"]) or {}
        refs[d["condition_id"]] = {
            "practitioner_reference": c.get("practitioner_reference", {}),
            "patient_guidance": c.get("patient_guidance", {}),
            "literature": c.get("literature"),
            "papers": clinical.pack.evidence.get(c.get("evidence_key"), {}).get("papers", [])[:3],
            "typical_symptoms": c.get("symptoms", []),
            "age": c.get("age"),
            "sex_weight": c.get("sex_weight"),
        }
    audit(db, user.id, "encounter.view", "encounter", e.id)
    db.commit()
    return {
        "encounter": encounter_out(e),
        "patient": {
            "name": patient.full_name,
            "profile": profile_out(patient.profile) if patient.profile else None,
        },
        "history": patient_history(db, e.patient_id),
        "condition_references": refs,
        "ayurveda_profile": build_ayurveda(db, patient),
    }


@router.post("/encounters/{encounter_id}/examination")
def examination(
    encounter_id: str, body: ExaminationIn, user: Practitioner, db: DB, clinical: Clinical
) -> dict:
    """Record Ashtavidha pariksha findings and re-run the assessment with them."""
    e = _visible(db, user, encounter_id)
    e.inputs = {**e.inputs, "examination": {**e.inputs.get("examination", {}), **body.examination}}
    status_before = e.status
    run_assessment(e, clinical)
    e.status = status_before  # a re-assessment never re-opens or closes a case
    audit(db, user.id, "encounter.examination", "encounter", e.id, fields=sorted(body.examination))
    db.commit()
    return encounter_out(e)


@router.post("/encounters/{encounter_id}/review")
def review(
    encounter_id: str,
    body: ReviewIn,
    user: Practitioner,
    db: DB,
    clinical: Clinical,
    idem: Idempotent,
) -> dict:
    """Record the verdict. Send an ``Idempotency-Key`` so a retry cannot record it twice
    (each review row is a training label for the learning loop)."""
    if (replayed := idem.replay({"encounter_id": encounter_id, **body.model_dump()})) is not None:
        return replayed
    e = _visible(db, user, encounter_id)
    name = None
    if body.decision in ("confirmed", "revised"):
        cond = clinical.condition(body.condition_id)
        if cond is None:
            raise HTTPException(422, "confirmed / revised reviews need a valid condition_id")
        name = cond["name"]
    e.reviews.append(
        Review(
            practitioner_id=user.id,
            decision=body.decision,
            condition_id=body.condition_id,
            condition_name=name,
            examination=e.inputs.get("examination"),
            notes=body.notes,
            plan=body.plan,
        )
    )
    e.status, e.practitioner_id = "reviewed", user.id
    audit(
        db,
        user.id,
        "encounter.review",
        "encounter",
        e.id,
        decision=body.decision,
        condition_id=body.condition_id,
    )
    db.flush()  # assigns the review's id and timestamp before the response is built
    return idem.commit(200, encounter_out(e))


@router.get("/insights")
def insights(user: Practitioner, db: DB, clinical: Clinical) -> dict:
    return population_insights(db, clinical)


__all__ = ["Review", "router"]
