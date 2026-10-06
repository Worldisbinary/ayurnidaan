"""Application services: clinical engine lifecycle, geography, learning loop, insights."""

from __future__ import annotations

import threading
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import asdict, fields
from datetime import UTC, date, datetime, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clinical import evaluation
from ..clinical.differential import DifferentialModel, Feedback
from ..clinical.dosha import vikriti as vikriti_fn
from ..clinical.engine import AssessmentEngine, EncounterInput
from ..clinical.kala_desha import classify_desha, kala_desha
from ..clinical.knowledge import KnowledgePack
from ..config import Settings
from ..http import get_json
from .models import AuditLog, Consent, Encounter, LocationClimate, ModelVersion, Review, User

LEARNING_DECISIONS = ("confirmed", "revised")
MIN_CASES_TO_LEARN = 20
K_ANONYMITY = 5


# --- audit / consent --------------------------------------------------------------------
def audit(
    s: Session,
    actor: str | None,
    action: str,
    entity: str | None = None,
    entity_id: str | None = None,
    **details,
) -> None:
    s.add(
        AuditLog(
            actor_id=actor,
            action=action,
            entity=entity,
            entity_id=entity_id,
            details=details or None,
        )
    )


def current_consents(s: Session, user_id: str) -> dict[str, bool]:
    rows = s.scalars(select(Consent).where(Consent.user_id == user_id).order_by(Consent.id)).all()
    out: dict[str, bool] = {}
    for r in rows:
        out[r.purpose] = r.granted
    return out


# --- encounter input (de)serialisation ------------------------------------------------------
def to_input(d: dict) -> EncounterInput:
    allowed = {f.name for f in fields(EncounterInput)}
    data = {k: v for k, v in d.items() if k in allowed}
    if isinstance(data.get("on_date"), str):
        data["on_date"] = date.fromisoformat(data["on_date"])
    return EncounterInput(**data)


def from_input(enc: EncounterInput) -> dict:
    d = asdict(enc)
    d["on_date"] = enc.on_date.isoformat()
    return d


def age_on(dob: date | None, on: date) -> float | None:
    if dob is None:
        return None
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


# --- clinical engine lifecycle ------------------------------------------------------------
class ClinicalService:
    """Holds the engine; swaps in a new learned model atomically on promotion."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.pack = KnowledgePack.load(settings.knowledge_dir)
        self._lock = threading.Lock()
        self.engine = AssessmentEngine(self.pack)
        self.active_version: str | None = None

    def load_active(self, s: Session) -> None:
        mv = s.scalars(select(ModelVersion).where(ModelVersion.active)).first()
        if mv is None:
            return
        cases = learning_cases(s, ids=set(mv.case_ids))
        with self._lock:
            self.engine = AssessmentEngine(self.pack, Feedback.from_cases(cases))
            self.active_version = mv.version

    def assess(self, enc: EncounterInput) -> dict:
        with self._lock:
            engine = self.engine
        return engine.assess(enc)


# --- geography ------------------------------------------------------------------------------
def _http_json(url: str, timeout: float = 20) -> dict:
    return get_json(url, timeout=timeout)


def geocode(settings: Settings, query: str, limit: int = 5) -> list[dict]:
    q = {"name": query, "count": limit, "language": "en", "format": "json"}
    if settings.geocode_country:
        q["countryCode"] = settings.geocode_country
    params = urllib.parse.urlencode(q)
    data = _http_json(f"{settings.open_meteo_geocode_url}?{params}")
    return [
        {
            "name": r.get("name"),
            "state": r.get("admin1"),
            "district": r.get("admin2"),
            "country": r.get("country_code"),
            "latitude": r["latitude"],
            "longitude": r["longitude"],
        }
        for r in data.get("results", [])
    ]


def round_cell(lat: float, lon: float) -> tuple[float, float, str]:
    la, lo = round(lat, 1), round(lon, 1)
    return la, lo, f"{la:.1f},{lo:.1f}"


def climate_for(s: Session, settings: Settings, lat: float, lon: float) -> LocationClimate:
    """Desha from the last full year of ERA5 reanalysis for the 0.1-degree cell (cached)."""
    la, lo, cell = round_cell(lat, lon)
    cached = s.get(LocationClimate, cell)
    if cached and cached.fetched_at.replace(tzinfo=cached.fetched_at.tzinfo or UTC) > datetime.now(
        UTC
    ) - timedelta(days=365):
        return cached
    year = datetime.now(UTC).year - 1
    params = urllib.parse.urlencode(
        {
            "latitude": la,
            "longitude": lo,
            "start_date": f"{year}-01-01",
            "end_date": f"{year}-12-31",
            "daily": "precipitation_sum,relative_humidity_2m_mean,temperature_2m_mean",
            "timezone": "auto",
        }
    )
    daily = _http_json(f"{settings.open_meteo_archive_url}?{params}")["daily"]
    precip = float(sum(x or 0 for x in daily["precipitation_sum"]))
    rh = [x for x in daily["relative_humidity_2m_mean"] if x is not None]
    temp = [x for x in daily["temperature_2m_mean"] if x is not None]
    row = cached or LocationClimate(cell=cell)
    row.annual_precip_mm, row.mean_rh = round(precip, 1), round(float(np.mean(rh)), 1)
    row.mean_temp_c = round(float(np.mean(temp)), 1)
    row.desha = classify_desha(row.annual_precip_mm, row.mean_rh)
    row.fetched_at = datetime.now(UTC)
    s.merge(row)
    return row


# --- learning loop ------------------------------------------------------------------------
def learning_cases(s: Session, ids: set[int] | None = None) -> list[dict]:
    """Confirmed / revised diagnoses whose patient has research consent in force."""
    q = (
        select(Review, Encounter)
        .join(Encounter, Review.encounter_id == Encounter.id)
        .where(Review.decision.in_(LEARNING_DECISIONS), Review.condition_id.is_not(None))
        .order_by(Review.created_at, Review.id)
    )
    consent_cache: dict[str, bool] = {}
    out = []
    for review, enc in s.execute(q).all():
        if ids is not None and review.id not in ids:
            continue
        if enc.patient_id not in consent_cache:
            consent_cache[enc.patient_id] = current_consents(s, enc.patient_id).get(
                "research", False
            )
        if not consent_cache[enc.patient_id]:
            continue
        out.append(
            {
                "review_id": review.id,
                "condition_id": review.condition_id,
                "condition_name": review.condition_name,
                "answers": dict(enc.inputs.get("symptoms", {})),
                "age": enc.inputs.get("age"),
                "sex": enc.inputs.get("sex"),
            }
        )
    return out


def _holdout_metrics(model: DifferentialModel, cases: list[dict]) -> dict:
    ranks = []
    for c in cases:
        present = [k for k, v in c["answers"].items() if v]
        vik = vikriti_fn(model.pack.vikriti, present)
        post = model.posterior(model.log_scores(c["answers"], c["age"], c["sex"], vik))
        names = [x["name"].casefold() for x in model.conditions]
        target = (c["condition_name"] or "").casefold()
        order, seen, rank = np.argsort(-post), set(), 0
        for j in order:
            if names[j] in seen:
                continue
            seen.add(names[j])
            rank += 1
            if names[j] == target or model.conditions[j]["id"] == c["condition_id"]:
                break
        ranks.append(rank)
    a = np.array(ranks) if ranks else np.array([np.inf])
    return {"n": len(ranks), "top1": float((a <= 1).mean()), "top5": float((a <= 5).mean())}


def retrain(s: Session, clinical: ClinicalService, actor: str) -> dict:
    """Fit a candidate on consented confirmed cases; promote only if it is not worse.

    Gate: on the newest 20 % of cases (time-based holdout) the candidate's top-5 must be
    >= the active model's, and on simulated textbook patients it may not lose more than
    2 points of top-5 (protects rare conditions that real cases have not covered yet).
    """
    cases = learning_cases(s)
    if len(cases) < MIN_CASES_TO_LEARN:
        return {
            "promoted": False,
            "reason": f"need >= {MIN_CASES_TO_LEARN} consented confirmed cases",
            "available": len(cases),
        }
    cut = int(len(cases) * 0.8)
    train, holdout = cases[:cut], cases[cut:]
    active = s.scalars(select(ModelVersion).where(ModelVersion.active)).first()
    current_cases = learning_cases(s, ids=set(active.case_ids)) if active else []
    current_train = [c for c in current_cases if c["review_id"] in {t["review_id"] for t in train}]
    current = DifferentialModel(clinical.pack, Feedback.from_cases(current_train))
    candidate = DifferentialModel(clinical.pack, Feedback.from_cases(train))
    cur_h, cand_h = _holdout_metrics(current, holdout), _holdout_metrics(candidate, holdout)
    sim_cfg = evaluation.SimConfig(n_questions=3)
    cur_sim = evaluation.simulate(current, sim_cfg, n=150, seed=7)["after_interview"]
    cand_sim = evaluation.simulate(candidate, sim_cfg, n=150, seed=7)["after_interview"]
    ok = cand_h["top5"] >= cur_h["top5"] and cand_sim["top5"] >= cur_sim["top5"] - 0.02
    metrics = {
        "holdout_current": cur_h,
        "holdout_candidate": cand_h,
        "simulated_current": cur_sim,
        "simulated_candidate": cand_sim,
    }
    if not ok:
        audit(s, actor, "learning.rejected", metrics=metrics)
        s.commit()
        return {
            "promoted": False,
            "reason": "candidate did not beat the active model",
            "metrics": metrics,
        }
    version = f"{clinical.pack.version}+fb{len(cases)}-{datetime.now(UTC):%Y%m%d%H%M%S}"
    for mv in s.scalars(select(ModelVersion).where(ModelVersion.active)).all():
        mv.active = False
    s.add(
        ModelVersion(
            version=version,
            pack_version=clinical.pack.version,
            n_cases=len(cases),
            case_ids=[c["review_id"] for c in cases],
            metrics=metrics,
            active=True,
        )
    )
    audit(s, actor, "learning.promoted", entity="model", entity_id=version, n_cases=len(cases))
    s.commit()
    clinical.load_active(s)
    return {"promoted": True, "version": version, "metrics": metrics}


# --- insights / pattern mining --------------------------------------------------------------
def patient_history(s: Session, user_id: str) -> dict:
    encs = s.scalars(
        select(Encounter).where(Encounter.patient_id == user_id).order_by(Encounter.created_at)
    ).all()
    timeline, by_condition = [], defaultdict(list)
    for e in encs:
        top = (e.assessment or {}).get("differential") or []
        confirmed = next(
            (
                r
                for r in sorted(e.reviews, key=lambda r: r.created_at)[::-1]
                if r.decision in LEARNING_DECISIONS
            ),
            None,
        )
        label = confirmed.condition_name if confirmed else (top[0]["name"] if top else None)
        vik = (e.assessment or {}).get("vikriti")
        timeline.append(
            {
                "encounter_id": e.id,
                "date": e.created_at.date().isoformat(),
                "ritu": e.ritu,
                "status": e.status,
                "triage": e.triage_level,
                "label": label,
                "confirmed": bool(confirmed),
                "vikriti": vik["shares"] if vik else None,
            }
        )
        if label:
            by_condition[label].append(e)
    recurring = [
        {"condition": k, "episodes": len(v), "ritus": dict(Counter(x.ritu for x in v))}
        for k, v in by_condition.items()
        if len(v) >= 2
    ]
    seasonal = [r for r in recurring if any(n >= 2 for n in r["ritus"].values())]
    shares = [t["vikriti"] for t in timeline if t["vikriti"]]
    trend = None
    if len(shares) >= 2:
        first, last = shares[0], shares[-1]
        trend = {d: round(last[d] - first[d], 3) for d in ("vata", "pitta", "kapha")}
    return {
        "encounters": timeline,
        "recurring": recurring,
        "seasonal_recurrence": seasonal,
        "vikriti_trend": trend,
    }


def population_insights(s: Session, clinical: ClinicalService) -> dict:
    """Confirmed-diagnosis patterns by season, habitat and region; cells under k are
    suppressed so no small group of patients can be singled out."""
    by_id = {c["id"]: c for c in clinical.pack.conditions}
    rows = s.execute(
        select(Review.condition_id, Encounter.ritu, Encounter.desha, Encounter.patient_id)
        .join(Encounter, Review.encounter_id == Encounter.id)
        .where(Review.decision.in_(LEARNING_DECISIONS))
    ).all()
    ritu_system, desha_dosha, ritu_condition = Counter(), Counter(), Counter()
    for cid, ritu, desha, _ in rows:
        c = by_id.get(cid)
        if not c:
            continue
        ritu_system[(ritu, c["body_system"])] += 1
        ritu_condition[(ritu, c["name"])] += 1
        for d in c["dosha_components"]:
            desha_dosha[(desha, d)] += 1

    def table(counter, keys):
        return [
            dict(zip(keys, k, strict=True)) | {"count": n}
            for k, n in counter.most_common()
            if n >= K_ANONYMITY
        ]

    return {
        "k_anonymity": K_ANONYMITY,
        "n_confirmed": len(rows),
        "ritu_body_system": table(ritu_system, ("ritu", "body_system")),
        "desha_dosha": table(desha_dosha, ("desha", "dosha")),
        "ritu_condition": table(ritu_condition, ("ritu", "condition")),
    }


def encounter_context(enc_input: EncounterInput) -> tuple[str, str | None]:
    kd = kala_desha(enc_input.on_date, enc_input.desha)
    return kd.ritu, kd.desha


__all__ = [
    "ClinicalService",
    "User",
    "audit",
    "climate_for",
    "current_consents",
    "geocode",
    "learning_cases",
    "patient_history",
    "population_insights",
    "retrain",
]
