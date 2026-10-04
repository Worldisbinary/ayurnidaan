"""Practitioner workspace: triaged queue, full case view, pariksha, diagnosis review."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import case, or_, select

from ..deps import DB, Clinical, Practitioner
from ..models import Encounter, Review, User
from ..schemas import ExaminationIn, ReviewIn
from ..services import audit, current_consents, patient_history, population_insights
from .encounters import encounter_out, run_assessment
from .me import profile_out

router = APIRouter(prefix="/practitioner", tags=["practitioner"])

_PRIORITY = case(
    (Encounter.triage_level == "emergency", 0), (Encounter.triage_level == "urgent", 1), else_=2
)


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
def queue(user: Practitioner, db: DB, status: str = "submitted") -> list[dict]:
    """Emergency and urgent cases first, then oldest first."""
    rows = db.scalars(
        select(Encounter)
        .where(
            Encounter.status == status,
            or_(Encounter.practitioner_id.is_(None), Encounter.practitioner_id == user.id),
        )
        .order_by(_PRIORITY, Encounter.created_at)
    ).all()
    out = []
    for e in rows:
        top = ((e.assessment or {}).get("differential") or [{}])[0]
        patient = db.get(User, e.patient_id)
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
    by_id = {c["id"]: c for c in clinical.pack.conditions}
    refs = {}
    for d in (e.assessment or {}).get("differential", [])[:8]:
        c = by_id.get(d["condition_id"], {})
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
    encounter_id: str, body: ReviewIn, user: Practitioner, db: DB, clinical: Clinical
) -> dict:
    e = _visible(db, user, encounter_id)
    name = None
    if body.decision in ("confirmed", "revised"):
        cond = next((c for c in clinical.pack.conditions if c["id"] == body.condition_id), None)
        if cond is None:
            raise HTTPException(422, "confirmed / revised reviews need a valid condition_id")
        name = cond["name"]
    db.add(
        Review(
            encounter_id=e.id,
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
    db.commit()
    db.refresh(e)
    return encounter_out(e)


@router.get("/insights")
def insights(user: Practitioner, db: DB, clinical: Clinical) -> dict:
    return population_insights(db, clinical)


__all__ = ["Review", "router"]
