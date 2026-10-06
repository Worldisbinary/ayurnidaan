"""Patient self-service: profile, location (Desha), consents, Prakriti, history, DPDP rights."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ...clinical import dosha
from ..deps import DB, AppSettings, Clinical, CurrentUser, Patient
from ..models import Consent, Encounter, PatientProfile
from ..schemas import ConsentIn, LocationIn, PrakritiIn, ProfileIn
from ..services import audit, climate_for, current_consents, patient_history, round_cell

router = APIRouter(prefix="/me", tags=["me"])


def _profile(user) -> PatientProfile:
    if user.profile is None:
        user.profile = PatientProfile()
    return user.profile


def profile_out(p: PatientProfile) -> dict:
    return {
        "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
        "sex": p.sex,
        "state": p.state,
        "district": p.district,
        "desha": p.desha,
        "climate": p.climate,
        "prakriti": p.prakriti_result,
        "prakriti_answers": p.prakriti_answers,
        "chronic_conditions": p.chronic_conditions or [],
        "current_medicines": p.current_medicines or [],
        "location_cell": [p.lat_round, p.lon_round] if p.lat_round is not None else None,
    }


@router.get("/profile")
def get_profile(user: Patient) -> dict:
    return profile_out(_profile(user))


@router.put("/profile")
def put_profile(body: ProfileIn, user: Patient, db: DB) -> dict:
    p = _profile(user)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    audit(db, user.id, "profile.update", "user", user.id)
    db.commit()
    return profile_out(p)


@router.put("/location")
def put_location(body: LocationIn, user: Patient, db: DB, settings: AppSettings) -> dict:
    """Coarse location -> Desha (habitat) from local climate. Requires location consent."""
    if not current_consents(db, user.id).get("location"):
        raise HTTPException(403, "location consent required")
    p = _profile(user)
    p.lat_round, p.lon_round, _ = round_cell(body.latitude, body.longitude)
    p.state, p.district = body.state or p.state, body.district or p.district
    try:
        c = climate_for(db, settings, body.latitude, body.longitude)
    except Exception as exc:  # climate service down: keep location, desha unknown
        audit(db, user.id, "location.climate_failed", "user", user.id, error=str(exc)[:200])
        db.commit()
        raise HTTPException(503, "climate service unavailable, try again later") from exc
    p.desha = c.desha
    p.climate = {
        "annual_precip_mm": c.annual_precip_mm,
        "mean_rh": c.mean_rh,
        "mean_temp_c": c.mean_temp_c,
    }
    audit(db, user.id, "location.update", "user", user.id, cell=c.cell)
    db.commit()
    return profile_out(p)


@router.get("/consents")
def get_consents(user: CurrentUser, db: DB, settings: AppSettings) -> dict:
    return {"policy_version": settings.policy_version, "consents": current_consents(db, user.id)}


@router.post("/consents")
def post_consent(body: ConsentIn, user: CurrentUser, db: DB, settings: AppSettings) -> dict:
    db.add(
        Consent(
            user_id=user.id,
            purpose=body.purpose,
            granted=body.granted,
            policy_version=settings.policy_version,
        )
    )
    if body.purpose == "location" and not body.granted and user.profile:
        user.profile.lat_round = user.profile.lon_round = None  # withdrawal erases the cell
    audit(
        db,
        user.id,
        "consent." + ("grant" if body.granted else "withdraw"),
        "user",
        user.id,
        purpose=body.purpose,
    )
    db.commit()
    return {"policy_version": settings.policy_version, "consents": current_consents(db, user.id)}


@router.post("/prakriti")
def post_prakriti(body: PrakritiIn, user: Patient, db: DB, clinical: Clinical) -> dict:
    result = dosha.prakriti(clinical.pack.prakriti, body.answers)
    if result is None:
        raise HTTPException(422, "no recognised answers")
    p = _profile(user)
    p.prakriti_answers, p.prakriti_result = body.answers, result.to_dict()
    # keep the modules registry in step, so "Prakriti - quick" shows as completed
    now = datetime.now(UTC).isoformat(timespec="seconds")
    p.modules = {
        **(p.modules or {}),
        "prakriti_quick": {
            "answers": body.answers,
            "result": p.prakriti_result,
            "completed_at": now,
            "history": [{"at": now}],
        },
    }
    audit(db, user.id, "prakriti.assess", "user", user.id)
    db.commit()
    return p.prakriti_result


@router.get("/history")
def history(user: Patient, db: DB) -> dict:
    return patient_history(db, user.id)


@router.get("/export")
def export(user: CurrentUser, db: DB) -> dict:
    """DPDP right of access: everything stored about the user, machine-readable."""
    encs = db.scalars(select(Encounter).where(Encounter.patient_id == user.id)).all()
    consents = db.scalars(select(Consent).where(Consent.user_id == user.id)).all()
    audit(db, user.id, "data.export", "user", user.id)
    db.commit()
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "created_at": user.created_at.isoformat(),
        },
        "profile": profile_out(user.profile) if user.profile else None,
        "consents": [
            {
                "purpose": c.purpose,
                "granted": c.granted,
                "policy_version": c.policy_version,
                "at": c.created_at.isoformat(),
            }
            for c in consents
        ],
        "encounters": [
            {
                "id": e.id,
                "created_at": e.created_at.isoformat(),
                "status": e.status,
                "inputs": e.inputs,
                "assessment": e.assessment,
                "reviews": [
                    {
                        "decision": r.decision,
                        "condition": r.condition_name,
                        "notes": r.notes,
                        "plan": r.plan,
                    }
                    for r in e.reviews
                ],
            }
            for e in encs
        ],
    }


@router.delete("", status_code=204)
def erase(user: CurrentUser, db: DB) -> None:
    """DPDP right to erasure: deletes the account and all linked health data (cascade).
    The audit trail keeps only the pseudonymous id of the erasure event."""
    uid = user.id
    db.delete(user)
    audit(db, uid, "account.erase", "user", uid)
    db.commit()
