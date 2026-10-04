from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..deps import DB, Admin, Clinical
from ..models import AuditLog, ModelVersion, User
from ..services import audit, learning_cases, retrain

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/practitioners")
def practitioners(user: Admin, db: DB, pending: bool = True) -> list[dict]:
    q = select(User).where(User.role == "practitioner")
    if pending:
        q = q.where(User.practitioner_verified.is_(False))
    return [
        {
            "id": u.id,
            "full_name": u.full_name,
            "email": u.email,
            "registration_number": u.registration_number,
            "verified": u.practitioner_verified,
            "created_at": u.created_at.isoformat(),
        }
        for u in db.scalars(q).all()
    ]


@router.post("/practitioners/{user_id}/verify")
def verify(user_id: str, user: Admin, db: DB, approve: bool = True) -> dict:
    """Approve after checking the registration number against the State / NCISM register."""
    target = db.get(User, user_id)
    if target is None or target.role != "practitioner":
        raise HTTPException(404, "practitioner not found")
    target.practitioner_verified = approve
    audit(
        db, user.id, "practitioner.verify" if approve else "practitioner.unverify", "user", user_id
    )
    db.commit()
    return {"id": user_id, "verified": approve}


@router.get("/learning")
def learning_status(user: Admin, db: DB, clinical: Clinical) -> dict:
    versions = db.scalars(select(ModelVersion).order_by(ModelVersion.id.desc()).limit(10)).all()
    return {
        "active_version": clinical.engine.version,
        "eligible_cases": len(learning_cases(db)),
        "versions": [
            {
                "version": v.version,
                "n_cases": v.n_cases,
                "active": v.active,
                "metrics": v.metrics,
                "created_at": v.created_at.isoformat(),
            }
            for v in versions
        ],
    }


@router.post("/learning/retrain")
def run_retrain(user: Admin, db: DB, clinical: Clinical) -> dict:
    return retrain(db, clinical, user.id)


@router.get("/audit")
def audit_log(user: Admin, db: DB, limit: int = 200) -> list[dict]:
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))).all()
    return [
        {
            "at": r.created_at.isoformat(),
            "actor": r.actor_id,
            "action": r.action,
            "entity": r.entity,
            "entity_id": r.entity_id,
            "details": r.details,
        }
        for r in rows
    ]
