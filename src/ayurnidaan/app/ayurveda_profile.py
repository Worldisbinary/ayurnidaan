"""Everything known about a patient, organised the way an Ayurvedic assessment is.

Built for both the patient dashboard and the practitioner case view, from: the profile
(identity, location, modules), the latest check-up (vikriti, symptoms) and the last
7 days of Dinacharya / diet logs.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clinical import ayurveda
from ..clinical import modules as M
from ..clinical.guidance import DOSHA_HABITS
from ..clinical.kala_desha import kala_desha, upcoming_ritus
from .models import DailyLog, Encounter, PatientProfile, User
from .services import age_on

COMPLETENESS = [  # (id, label, weight)
    ("identity", "Date of birth, sex and district", 10),
    ("location", "Location (Desha)", 10),
    ("prakriti", "Prakriti questionnaire", 20),
    ("agni_mala", "Digestion & elimination", 15),
    ("ojas_bala", "Strength & immunity", 15),
    ("manas_prakriti", "Mental constitution", 10),
    ("dashavidha", "Body measures", 10),
    ("artava", "Menstrual health", 10),
    ("checkup", "At least one check-up", 5),
    ("dinacharya", "Daily routine logged 3+ days this week", 5),
]

TASTE_ADVICE = {  # tastes that pacify each dosha (CS Sutra 26)
    "vata": ["sweet", "sour", "salty"],
    "pitta": ["sweet", "bitter", "astringent"],
    "kapha": ["pungent", "bitter", "astringent"],
}


def _module_result(p: PatientProfile, mid: str) -> dict | None:
    m = (p.modules or {}).get(mid)
    return m["result"] if m else None


def latest_encounter(s: Session, user_id: str) -> Encounter | None:
    rows = s.scalars(
        select(Encounter)
        .where(Encounter.patient_id == user_id)
        .order_by(Encounter.created_at.desc())
    ).all()
    return next((e for e in rows if e.assessment and not e.assessment.get("stopped")), None)


def week_logs(s: Session, user_id: str, today: date) -> list[DailyLog]:
    return s.scalars(
        select(DailyLog)
        .where(DailyLog.user_id == user_id, DailyLog.day > today - timedelta(days=7))
        .order_by(DailyLog.day)
    ).all()


def _streak(s: Session, user_id: str, today: date) -> int:
    days = {d for (d,) in s.execute(select(DailyLog.day).where(DailyLog.user_id == user_id))}
    n, cursor = 0, today
    while cursor in days:
        n += 1
        cursor -= timedelta(days=1)
    return n


def build(s: Session, user: User, today: date | None = None) -> dict:
    today = today or date.today()
    p = user.profile or PatientProfile()
    mods = p.modules or {}
    age = age_on(p.date_of_birth, today)
    enc = latest_encounter(s, user.id)
    a = enc.assessment if enc else {}
    dash = _module_result(p, "dashavidha") or {}
    bmi = dash.get("bmi")
    present = [k for k, v in ((enc.inputs or {}).get("symptoms", {}) if enc else {}).items() if v]
    derived = ayurveda.derive(present, bmi).to_dict() if enc else None
    kd = kala_desha(today, p.desha)
    logs = week_logs(s, user.id, today)

    # diet over the week
    taste_totals = dict.fromkeys(M.RASA_EFFECT, 0)
    effect = dict.fromkeys(M.DOSHAS, 0)
    viruddha = []
    for log in logs:
        an = log.analysis or {}
        for t, n in an.get("tastes", {}).items():
            taste_totals[t] += n
        for d, v in an.get("dosha_effect", {}).items():
            effect[d] += v
        viruddha += [{"day": log.day.isoformat(), **f} for f in an.get("viruddha", [])]
    focus = (a.get("vikriti") or {}).get("dominant") or (p.prakriti_result or {}).get("dominant")
    focus_doshas = [d for d in (focus or "").split("-") if d in M.DOSHAS]
    good_tastes = sorted({t for d in focus_doshas for t in TASTE_ADVICE[d]})

    sections = {
        "identity": {
            "name": user.full_name,
            "age": age,
            "sex": p.sex,
            "state": p.state,
            "district": p.district,
            "verified": (p.identity or {}).get("verified", False),
            "source": (p.identity or {}).get("source"),
        },
        "vaya": ayurveda.vaya(age),
        "desha": {"desha": p.desha, "climate": p.climate},
        "kala": {
            "ritu": kd.ritu,
            "info": kd.ritu_info,
            "dosha_states": kd.dosha_states,
            "upcoming": upcoming_ritus(today, 2),
        },
        "dosha_clock": ayurveda.dosha_clock(),
        "prakriti": p.prakriti_result,
        "prakriti_source": "full"
        if "prakriti_full" in mods
        else "quick"
        if p.prakriti_result
        else None,
        "manas_prakriti": _module_result(p, "manas_prakriti"),
        "vikriti": a.get("vikriti"),
        "vikriti_date": enc.created_at.date().isoformat() if enc else None,
        "ayurveda": derived,
        "agni_mala": _module_result(p, "agni_mala"),
        "agni_latest": a.get("agni"),
        "ama": a.get("ama"),
        "ojas": _module_result(p, "ojas_bala"),
        "dashavidha": dash or None,
        "artava": _module_result(p, "artava") if p.sex == "female" else None,
        "dinacharya": {
            # the 7-day window (oldest first), so clients need no clock of their own
            "window": [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)],
            "days": [{"day": log.day.isoformat(), "score": log.score} for log in logs],
            "average": round(sum(log.score for log in logs) / len(logs)) if logs else None,
            "streak": _streak(s, user.id, today),
        },
        "diet": {
            "tastes": taste_totals,
            "dosha_effect": effect,
            "viruddha": viruddha[-10:],
            "favour_tastes": good_tastes,
            "focus_dosha": focus,
        },
    }

    done = {
        "identity": bool(p.date_of_birth and p.sex and p.district),
        "location": bool(p.desha),
        "prakriti": bool(p.prakriti_result),
        "agni_mala": "agni_mala" in mods,
        "ojas_bala": "ojas_bala" in mods,
        "manas_prakriti": "manas_prakriti" in mods,
        "dashavidha": "dashavidha" in mods,
        "artava": "artava" in mods,
        "checkup": enc is not None,
        "dinacharya": len(logs) >= 3,
    }
    applicable = [c for c in COMPLETENESS if not (c[0] == "artava" and p.sex != "female")]
    total = sum(w for _, _, w in applicable)
    got = sum(w for cid, _, w in applicable if done[cid])
    sections["completeness"] = {
        "score": round(100 * got / total),
        "items": [
            {"id": cid, "label": label, "weight": w, "done": done[cid]}
            for cid, label, w in applicable
        ],
    }
    sections["recommendations"] = recommendations(sections, focus_doshas)
    return sections


def recommendations(sec: dict, focus: list[str]) -> list[str]:
    """General, low-risk lifestyle pointers only (no herbs or doses)."""
    out = []
    nxt = sec["kala"]["upcoming"][0] if sec["kala"]["upcoming"] else None
    if nxt and nxt["days_away"] <= 30 and (nxt["aggravates"] or nxt["accumulates"]):
        d = ", ".join(nxt["aggravates"] or nxt["accumulates"])
        out.append(
            f"{nxt['ritu'].title()} begins in {nxt['days_away']} days and builds {d} - "
            "start adjusting diet and routine now (Ritu sandhi)."
        )
    for d in focus:
        out.extend(DOSHA_HABITS[d][:1])
    dina = sec["dinacharya"]
    if dina["average"] is not None and dina["average"] < 50:
        out.append("Your daily routine score is low - begin with fixed wake and meal times.")
    if sec["diet"]["viruddha"]:
        out.append("Some meals combined incompatible foods (Viruddha ahara) - see the diet log.")
    ojas = sec["ojas"] or {}
    if ojas.get("bala") == "avara":
        out.append(
            "Low Ojas: prioritise sleep, regular nourishing meals and rest; discuss with a practitioner."
        )
    if sec["ama"] and sec["ama"].get("level") == "high":
        out.append("Signs of Ama: favour light, warm, freshly cooked food until appetite returns.")
    return out[:6]


def trends(s: Session, user: User) -> dict:
    encs = s.scalars(
        select(Encounter).where(Encounter.patient_id == user.id).order_by(Encounter.created_at)
    ).all()
    logs = s.scalars(
        select(DailyLog).where(DailyLog.user_id == user.id).order_by(DailyLog.day)
    ).all()
    p = user.profile or PatientProfile()
    ojas_hist = ((p.modules or {}).get("ojas_bala") or {}).get("history", [])
    return {
        "checkups": [
            {
                "date": e.created_at.date().isoformat(),
                "vikriti": (e.assessment.get("vikriti") or {}).get("shares"),
                "ama": (e.assessment.get("ama") or {}).get("level"),
                "agni": e.assessment.get("agni"),
            }
            for e in encs
            if e.assessment and not e.assessment.get("stopped")
        ],
        "dinacharya": [
            {
                "date": log.day.isoformat(),
                "score": log.score,
                "dosha_effect": (log.analysis or {}).get("dosha_effect"),
            }
            for log in logs
        ],
        "ojas": [{"date": h["at"][:10], "score": h.get("ojas_score")} for h in ojas_hist],
    }
