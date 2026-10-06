"""Ayurvedic profile, optional questionnaire modules, daily tracking and DigiLocker."""

from __future__ import annotations

import html
import urllib.parse
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ...clinical import modules as M
from .. import digilocker as dl
from ..ayurveda_profile import build, trends
from ..deps import DB, AppSettings, Clinical, Patient
from ..models import Consent, DailyLog, OAuthState, PatientProfile, User
from ..services import audit

router = APIRouter(tags=["ayurveda"])


class ModuleAnswersIn(BaseModel):
    answers: dict[str, str | float] = Field(max_length=40)


class DailyIn(BaseModel):
    dinacharya: dict[str, bool] = Field(default_factory=dict, max_length=20)
    meals: dict[Literal["breakfast", "lunch", "dinner"], list[str]] = Field(default_factory=dict)


class DigiLockerStartIn(BaseModel):
    return_to: str = Field(max_length=500)


def _profile(user: User) -> PatientProfile:
    if user.profile is None:
        user.profile = PatientProfile()
    return user.profile


def _modules_for(clinical, user: User) -> dict[str, M.Module]:
    sex = user.profile.sex if user.profile else None
    return {k: m for k, m in M.registry(clinical.pack).items() if m.sex in (None, sex)}


# --- profile & trends -------------------------------------------------------------------------
@router.get("/me/ayurveda")
def my_profile(user: Patient, db: DB) -> dict:
    return build(db, user)


@router.get("/me/trends")
def my_trends(user: Patient, db: DB) -> dict:
    return trends(db, user)


# --- questionnaire modules --------------------------------------------------------------------
@router.get("/questionnaires")
def questionnaires(user: Patient, clinical: Clinical) -> list[dict]:
    done = (user.profile.modules or {}) if user.profile else {}
    return [
        {**m.to_dict(), "completed_at": (done.get(k) or {}).get("completed_at")}
        for k, m in _modules_for(clinical, user).items()
    ]


@router.post("/me/modules/{module_id}")
def submit_module(
    module_id: str, body: ModuleAnswersIn, user: Patient, db: DB, clinical: Clinical
) -> dict:
    module = _modules_for(clinical, user).get(module_id)
    if module is None:
        raise HTTPException(404, "questionnaire not found")
    try:
        result = module.score(body.answers)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    p = _profile(user)
    mods = dict(p.modules or {})
    now = datetime.now(UTC).isoformat(timespec="seconds")
    history = (mods.get(module_id) or {}).get("history", [])
    summary = {k: v for k, v in result.items() if isinstance(v, (int, float, str))}
    mods[module_id] = {
        "answers": body.answers,
        "result": result,
        "completed_at": now,
        "history": [*history, {"at": now, **summary}][-24:],
    }
    p.modules = mods  # reassign so SQLAlchemy sees the JSON change
    if module_id in ("prakriti_quick", "prakriti_full") and result:
        p.prakriti_answers, p.prakriti_result = dict(body.answers), result
    audit(db, user.id, "module.submit", "module", module_id)
    db.commit()
    return result


# --- daily tracking ---------------------------------------------------------------------------
@router.get("/daily/catalog")
def daily_catalog() -> dict:
    return M.catalog()


@router.put("/me/daily/{day}")
def put_daily(day: date, body: DailyIn, user: Patient, db: DB) -> dict:
    today = date.today()
    if day > today or day < today - timedelta(days=30):
        raise HTTPException(422, "you can log today or up to 30 days back")
    unknown = [f for foods in body.meals.values() for f in foods if f not in M.FOODS]
    unknown += [k for k in body.dinacharya if k not in M.DINACHARYA]
    if unknown:
        raise HTTPException(422, f"unknown items: {sorted(set(unknown))}")
    log = db.scalar(select(DailyLog).where(DailyLog.user_id == user.id, DailyLog.day == day))
    if log is None:
        log = DailyLog(user_id=user.id, day=day)
        db.add(log)
    log.dinacharya, log.meals = body.dinacharya, dict(body.meals)
    log.score = M.dinacharya_score(body.dinacharya)
    log.analysis = M.analyse_meals(dict(body.meals))
    db.commit()
    return {
        "day": day.isoformat(),
        "score": log.score,
        "dinacharya": log.dinacharya,
        "meals": log.meals,
        "analysis": log.analysis,
    }


@router.get("/me/daily")
def list_daily(user: Patient, db: DB, days: int = Query(14, ge=1, le=90)) -> list[dict]:
    since = date.today() - timedelta(days=days)
    rows = db.scalars(
        select(DailyLog)
        .where(DailyLog.user_id == user.id, DailyLog.day > since)
        .order_by(DailyLog.day.desc())
    ).all()
    return [
        {
            "day": r.day.isoformat(),
            "score": r.score,
            "dinacharya": r.dinacharya,
            "meals": r.meals,
            "analysis": r.analysis,
        }
        for r in rows
    ]


# --- DigiLocker -------------------------------------------------------------------------------
@router.get("/digilocker/status")
def digilocker_status(settings: AppSettings) -> dict:
    return {"mode": settings.digilocker_effective_mode}


@router.post("/me/digilocker/start")
def digilocker_start(body: DigiLockerStartIn, user: Patient, db: DB, settings: AppSettings) -> dict:
    prov = dl.provider(settings)
    if prov is None:
        raise HTTPException(404, "DigiLocker is not enabled")
    if not dl.allowed_return(settings, body.return_to):
        raise HTTPException(422, "return_to is not an allowed app URL")
    verifier, challenge = dl.pkce_pair()
    state = dl.secrets.token_urlsafe(32)
    db.add(
        OAuthState(
            state=state,
            user_id=user.id,
            provider="digilocker",
            code_verifier=verifier,
            return_to=body.return_to,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    db.commit()
    return {"authorize_url": prov.authorize_url(state, challenge), "mode": prov.mode}


@router.get("/digilocker/sandbox/authorize", response_class=HTMLResponse)
def digilocker_sandbox(settings: AppSettings, state: str, redirect_uri: str) -> HTMLResponse:
    if settings.digilocker_effective_mode != "sandbox":
        raise HTTPException(404)
    sandbox = dl.SandboxProvider(settings)
    if redirect_uri != sandbox.callback_url():
        raise HTTPException(422, "unexpected redirect_uri")
    # `state` comes from the query string: URL-encode it into the links and HTML-escape the
    # result, or it is a reflected-XSS vector on this page.
    q = urllib.parse.urlencode
    allow = f"{redirect_uri}?{q({'state': state, 'code': f'sandbox-{dl.secrets.token_hex(8)}'})}"
    deny = f"{redirect_uri}?{q({'state': state, 'error': 'access_denied'})}"
    page = dl.SANDBOX_PAGE.format(allow=html.escape(allow), deny=html.escape(deny))
    # Static page: inline styles only, no scripts, cannot be framed.
    csp = (
        "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; form-action 'none'"
    )
    return HTMLResponse(page, headers={"Content-Security-Policy": csp})


def _back(return_to: str, outcome: str) -> RedirectResponse:
    sep = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{return_to}{sep}digilocker={outcome}", status_code=303)


@router.get("/digilocker/callback")
def digilocker_callback(
    db: DB, settings: AppSettings, state: str, code: str | None = None, error: str | None = None
) -> RedirectResponse:
    row = db.get(OAuthState, state)
    if row is None:
        raise HTTPException(400, "unknown or used state")
    db.delete(row)  # one-time use
    db.commit()
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        return _back(row.return_to, "expired")
    if error or not code:
        return _back(row.return_to, "denied")
    prov = dl.provider(settings)
    user = db.get(User, row.user_id)
    if prov is None or user is None:
        return _back(row.return_to, "error")
    try:
        ident = prov.identity(prov.exchange(code, row.code_verifier), account_name=user.full_name)
    except Exception as exc:
        audit(db, user.id, "digilocker.failed", "user", user.id, error=type(exc).__name__)
        db.commit()
        return _back(row.return_to, "error")
    p = _profile(user)
    filled = []
    for field, value in (
        ("date_of_birth", ident.dob),
        ("sex", ident.sex if ident.sex != "other" else None),
        ("state", ident.state),
        ("district", ident.district),
    ):
        if value:
            setattr(p, field, value)
            filled.append(field)
    p.identity = {
        "source": f"digilocker-{prov.mode}",
        "verified": prov.mode == "production",
        "verified_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "fields": filled,
        "name_matches_account": dl.names_match(ident.name, user.full_name),
    }
    db.add(
        Consent(
            user_id=user.id,
            purpose="identity",
            granted=True,
            policy_version=settings.policy_version,
        )
    )
    audit(db, user.id, "digilocker.linked", "user", user.id, mode=prov.mode, fields=filled)
    db.commit()
    return _back(row.return_to, "ok")
