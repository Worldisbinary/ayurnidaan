"""REST API (FastAPI). OpenAPI docs at /docs.

Auth: when ``AYUR_API_KEY`` is set every /v1 route requires header ``X-API-Key``.
"""

from __future__ import annotations

import hmac
import time
import uuid
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .config import get_settings
from .logging_utils import get_logger
from .service import AnalyticsService, ArtifactsMissing, get_service

log = get_logger(__name__)

app = FastAPI(
    title="Ayurnidaan Analytics API",
    version=__version__,
    description="Symptom clusters, screening, predictive variables and diabetes-risk triage.",
)


@app.middleware("http")
async def request_log(request: Request, call_next):
    rid = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
    t = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    log.info(
        "http",
        fields={
            "rid": rid,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": round((time.perf_counter() - t) * 1000, 1),
        },
    )
    return response


@app.exception_handler(ArtifactsMissing)
async def _missing(_: Request, exc: ArtifactsMissing):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def require_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().api_key
    if expected and not (x_api_key and hmac.compare_digest(x_api_key, expected)):
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


Service = Annotated[AnalyticsService, Depends(get_service)]
v1 = [Depends(require_key)]


# --- schemas ---------------------------------------------------------------------------
class PatientIntake(BaseModel):
    """Inputs of the deployed risk model. Unknown answers are allowed where they exist."""

    age: int = Field(ge=15, le=100)
    family_history: Literal["yes", "no", "unknown"]
    sleep_hours: float = Field(ge=0, le=24)
    dosha: Literal[
        "vata", "pitta", "kapha", "vata-pitta", "vata-kapha", "pitta-kapha", "tridosha", "unknown"
    ] = "unknown"
    gender: Literal["female", "male"] | None = None
    diet: Literal["vegetarian", "non-vegetarian", "vegan", "other"] | None = None
    stress_level: int | None = Field(default=None, ge=1, le=5)
    exercise: bool | None = None
    food_preferences: list[str] = Field(default_factory=list, examples=[["sweet", "oily"]])

    def to_features(self) -> dict:
        d = self.model_dump(exclude={"food_preferences"})
        prefs = {p.strip().casefold() for p in self.food_preferences}
        for tok in (
            "cooling",
            "dry",
            "heavy",
            "light",
            "oily",
            "pungent",
            "salty",
            "sour",
            "spicy",
            "sweet",
            "warming",
        ):
            d[f"pref_{tok}"] = float(tok in prefs)
        d["exercise"] = None if self.exercise is None else float(self.exercise)
        return d


class ScreeningRequest(BaseModel):
    answers: dict[str, bool] = Field(
        default_factory=dict, examples=[{"fever": True, "cough": True}]
    )
    max_questions: int = Field(default=12, ge=1, le=60)


# --- routes ----------------------------------------------------------------------------
@app.get("/health")
def health(svc: Service) -> dict:
    try:
        run_id = svc.run_summary["run_id"]
        return {"status": "ok", "version": __version__, "run_id": run_id}
    except ArtifactsMissing as exc:
        return {"status": "degraded", "version": __version__, "detail": str(exc)}


@app.get("/v1/kpis", dependencies=v1)
def kpis(svc: Service) -> dict:
    return svc.kpis()


@app.get("/v1/quality", dependencies=v1)
def quality_report(svc: Service) -> dict:
    return svc.quality


@app.get("/v1/dosha-overview", dependencies=v1)
def dosha_overview(svc: Service) -> list[dict]:
    return svc.dosha_overview()


@app.get("/v1/clusters", dependencies=v1)
def clusters(svc: Service) -> dict:
    c = svc.clusters
    return {k: v for k, v in c.items() if k != "edges"}


@app.get("/v1/clusters/{cluster_id}", dependencies=v1)
def cluster(cluster_id: int, svc: Service) -> dict:
    detail = svc.cluster_detail(cluster_id)
    if detail is None:
        raise HTTPException(404, f"cluster {cluster_id} not found")
    return detail


@app.get("/v1/variables", dependencies=v1)
def predictive_variables(svc: Service) -> dict:
    return svc.variables


@app.get("/v1/screening/questionnaire", dependencies=v1)
def questionnaire(svc: Service) -> dict:
    q = svc.screening["questionnaire"]
    return {
        k: q[k]
        for k in (
            "n_items",
            "recommended_k",
            "recommended_items",
            "full_accuracy",
            "recommended_accuracy",
        )
    }


@app.post("/v1/screening/next", dependencies=v1)
def screening_next(req: ScreeningRequest, svc: Service) -> dict:
    return svc.screen_next(req.answers, max_questions=req.max_questions)


@app.post("/v1/risk/score", dependencies=v1)
def risk_score(patient: PatientIntake, svc: Service) -> dict:
    return svc.score_risk(patient.to_features())


@app.get("/v1/model-card", dependencies=v1)
def model_card(svc: Service) -> dict:
    return svc.model_card


@app.post("/v1/admin/reload", dependencies=v1)
def reload(svc: Service) -> dict:
    svc.reload()
    return {"reloaded": True, "run_id": svc.run_summary["run_id"]}
