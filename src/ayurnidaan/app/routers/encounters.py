"""Patient encounters: emergency checklist -> adaptive interview -> share with practitioner."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import select, tuple_
from sqlalchemy.orm import selectinload

from ..deps import DB, Clinical, Patient
from ..idempotency import Idempotent
from ..models import TRIAGE_RANK, Encounter
from ..pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page
from ..schemas import AnswersIn, EncounterCreate
from ..services import age_on, audit, current_consents, encounter_context, to_input

router = APIRouter(prefix="/encounters", tags=["encounters"])


def encounter_out(e: Encounter, include_inputs: bool = True) -> dict:
    out = {
        "id": e.id,
        "status": e.status,
        "triage_level": e.triage_level,
        "chief_complaint": e.chief_complaint,
        "created_at": e.created_at.isoformat(),
        "ritu": e.ritu,
        "desha": e.desha,
        "engine_version": e.engine_version,
        "assessment": e.assessment,
        "reviews": [
            {
                "decision": r.decision,
                "condition_id": r.condition_id,
                "condition_name": r.condition_name,
                "notes": r.notes,
                "plan": r.plan,
                "created_at": r.created_at.isoformat(),
            }
            for r in e.reviews
        ],
    }
    if include_inputs:
        out["inputs"] = e.inputs
    return out


def profile_signals(p) -> dict:
    """Carry relevant module answers into the assessment: patient-reported stool/urine
    (counted as examination evidence until a practitioner examines) and BMI."""
    mods = (p.modules or {}) if p else {}
    digestion = (mods.get("agni_mala") or {}).get("answers", {})
    reported = {
        k: digestion[src]
        for k, src in (("mala", "stool"), ("mutra", "urine"))
        if digestion.get(src) and digestion[src] != "normal"
    }
    bmi = ((mods.get("dashavidha") or {}).get("result") or {}).get("bmi")
    agni = {
        "irregular": "irregular",
        "sharp": "sharp_frequent_hunger",
        "slow": "slow_heavy_after_meals",
        "balanced": "balanced",
    }.get(digestion.get("agni"))
    return {"reported_examination": reported, "bmi": bmi, "profile_agni": agni}


def run_assessment(e: Encounter, clinical) -> None:
    enc_input = to_input(e.inputs)
    result = clinical.assess(enc_input)
    e.assessment = result
    e.engine_version = result["engine_version"]
    e.triage_level = result["triage"]["level"]
    e.triage_rank = TRIAGE_RANK.get(e.triage_level, 2)
    e.ritu, e.desha = encounter_context(enc_input)
    if result.get("stopped"):
        e.status = "emergency"


def _own(db, user, encounter_id: str) -> Encounter:
    e = db.get(Encounter, encounter_id)
    if e is None or e.patient_id != user.id:
        raise HTTPException(404, "encounter not found")
    return e


@router.post("", status_code=201)
def create(
    body: EncounterCreate, user: Patient, db: DB, clinical: Clinical, idem: Idempotent
) -> dict:
    """Start a check-up. Send an ``Idempotency-Key`` header: a retry after a lost response
    then returns the same encounter instead of filing a duplicate case."""
    if (replayed := idem.replay(body.model_dump())) is not None:
        return replayed
    p = user.profile
    today = date.today()
    inputs = {
        "age": age_on(p.date_of_birth, today) if p else None,
        "sex": p.sex if p else None,
        "on_date": today.isoformat(),
        "desha": p.desha if p else None,
        "red_flag_checklist": body.red_flag_checklist,
        "symptoms": body.symptoms,
        "free_text_symptoms": body.free_text_symptoms,
        "prakriti_answers": (p.prakriti_answers or {}) if p else {},
        "examination": {},
        "aggravating": body.aggravating,
        "relieving": body.relieving,
        **profile_signals(p),
    }
    # the check-up's own answer wins; otherwise use the digestion module's
    inputs["agni"] = body.agni or inputs.pop("profile_agni")
    inputs.pop("profile_agni", None)
    e = Encounter(patient_id=user.id, chief_complaint=body.chief_complaint, inputs=inputs)
    run_assessment(e, clinical)
    # free text resolved to canonical symptoms is folded into the answers for next rounds
    e.inputs = {
        **inputs,
        "symptoms": {
            **body.symptoms,
            **{
                m["matched"]: True
                for m in e.assessment.get("free_text_mapping", [])
                if m["matched"]
            },
        },
        "free_text_symptoms": [],
    }
    db.add(e)
    db.flush()
    audit(db, user.id, "encounter.create", "encounter", e.id, triage=e.triage_level)
    return idem.commit(201, encounter_out(e))


@router.post("/{encounter_id}/answers")
def answer(encounter_id: str, body: AnswersIn, user: Patient, db: DB, clinical: Clinical) -> dict:
    e = _own(db, user, encounter_id)
    if e.status not in ("draft", "emergency"):
        raise HTTPException(409, f"encounter is {e.status}; answers are closed")
    inputs = dict(e.inputs)
    inputs["symptoms"] = {**inputs.get("symptoms", {}), **body.symptoms}
    inputs["free_text_symptoms"] = body.free_text_symptoms
    e.inputs = inputs
    run_assessment(e, clinical)
    e.inputs = {
        **inputs,
        "symptoms": {
            **inputs["symptoms"],
            **{
                m["matched"]: True
                for m in e.assessment.get("free_text_mapping", [])
                if m["matched"]
            },
        },
        "free_text_symptoms": [],
    }
    db.commit()
    return encounter_out(e)


@router.post("/{encounter_id}/submit")
def submit(encounter_id: str, user: Patient, db: DB) -> dict:
    """Share with practitioners. Requires consent to share data for care."""
    e = _own(db, user, encounter_id)
    if not current_consents(db, user.id).get("care"):
        raise HTTPException(403, "consent to share with a practitioner (care) is required")
    if e.status not in ("draft", "emergency"):
        raise HTTPException(409, f"encounter already {e.status}")
    e.status = "submitted"
    audit(db, user.id, "encounter.submit", "encounter", e.id)
    db.commit()
    return encounter_out(e)


@router.get("")
def list_mine(
    user: Patient,
    db: DB,
    response: Response,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
) -> list[dict]:
    """Newest first, keyset-paginated on (created_at, id) via ix_encounters_patient_created."""
    q = select(Encounter).where(Encounter.patient_id == user.id)
    if cursor:
        q = q.where(
            tuple_(Encounter.created_at, Encounter.id) < decode_cursor(cursor, (datetime, str))
        )
    rows = db.scalars(
        q.order_by(Encounter.created_at.desc(), Encounter.id.desc())
        .limit(limit + 1)
        .options(selectinload(Encounter.reviews))  # one query for all reviews, not N
    ).all()
    rows = page(list(rows), limit, lambda e: (e.created_at, e.id), response)
    return [encounter_out(e, include_inputs=False) for e in rows]


@router.get("/{encounter_id}")
def get_one(encounter_id: str, user: Patient, db: DB) -> dict:
    return encounter_out(_own(db, user, encounter_id))
