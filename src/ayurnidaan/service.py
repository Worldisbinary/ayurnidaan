"""Read-side service layer shared by the REST API and the dashboard.

Both front-ends call the same functions, so a number can never differ between the
API and the clinician view. Artifacts are loaded once and cached; ``reload()`` picks
up a new pipeline run without restarting the process.
"""

from __future__ import annotations

import json
import logging
import threading
from functools import cached_property
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from . import warehouse
from .analytics.risk import RiskModel
from .analytics.screening import AdaptiveScreener
from .config import Settings, get_settings

log = logging.getLogger(__name__)


class ArtifactsMissing(RuntimeError):
    pass


class AnalyticsService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._lock = threading.Lock()

    # --- loading -------------------------------------------------------------------
    def _path(self, name: str) -> Path:
        p = self.settings.artifacts_dir / name
        if not p.exists():
            raise ArtifactsMissing(f"{p.name} not found - run `ayur run` first")
        return p

    def _json(self, name: str) -> dict:
        return json.loads(self._path(name).read_text(encoding="utf-8"))

    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        with self._lock, warehouse.connect(self._path("warehouse.duckdb"), read_only=True) as con:
            return con.execute(sql, params or []).df()

    @cached_property
    def quality(self) -> dict:
        return self._json("quality_report.json")

    @cached_property
    def clusters(self) -> dict:
        return self._json("clusters.json")

    @cached_property
    def screening(self) -> dict:
        return self._json("screening.json")

    @cached_property
    def variables(self) -> dict:
        return self._json("variables.json")

    @cached_property
    def model_card(self) -> dict:
        return self._json("model_card.json")

    @cached_property
    def run_summary(self) -> dict:
        return self._json("run_summary.json")

    @cached_property
    def risk_model(self) -> RiskModel:
        import sklearn

        built = self.model_card.get("environment", {}).get("scikit-learn")
        if built and built != sklearn.__version__:
            log.warning(
                "model built with scikit-learn %s, running %s - re-run the pipeline",
                built,
                sklearn.__version__,
            )
        return joblib.load(self._path("risk_model.joblib"))

    @cached_property
    def screener(self) -> AdaptiveScreener:
        return joblib.load(self._path("screener.joblib"))

    @cached_property
    def condition_profiles(self) -> pd.DataFrame:
        return self.query(
            """SELECT c.condition_id, c.name, c.modern_equivalent, c.body_system, c.dosha,
                      c.namc_code, list(s.symptom) AS symptoms
               FROM dim_condition c JOIN bridge_condition_symptom b USING (condition_id)
               JOIN dim_symptom s USING (symptom_id)
               WHERE NOT c.profile_conflict GROUP BY ALL"""
        )

    def reload(self) -> None:
        for attr in list(vars(self)):
            if attr not in ("settings", "_lock"):
                delattr(self, attr)

    # --- read models ---------------------------------------------------------------
    def kpis(self) -> dict:
        counts = (
            self.query(
                """SELECT (SELECT COUNT(*) FROM fact_patient_intake) AS patients,
                      (SELECT COUNT(*) FROM fact_prakriti_assessment) AS assessments,
                      (SELECT COUNT(*) FROM dim_condition) AS conditions,
                      (SELECT COUNT(*) FROM dim_symptom) AS symptoms,
                      (SELECT COUNT(*) FROM dim_condition WHERE namc_tier IN ('exact','fuzzy'))
                          AS namc_coded_conditions"""
            )
            .iloc[0]
            .to_dict()
        )
        return {
            **{k: int(v) for k, v in counts.items()},
            "symptom_clusters": len(self.clusters["clusters"]),
            "sources_admitted": len(self.run_summary["admitted"]),
            "sources_rejected": len(self.run_summary["rejected"]),
            "risk_model_auc": self.model_card["holdout"]["auc"],
            "questionnaire_items": f"{self.screening['questionnaire']['recommended_k']}/"
            f"{self.screening['questionnaire']['n_items']}",
            "run_id": self.run_summary["run_id"],
        }

    def dosha_overview(self) -> list[dict]:
        return self.query("SELECT * FROM v_dosha_overview").to_dict("records")

    def cluster_detail(self, cluster_id: int, limit: int = 10) -> dict | None:
        match = [c for c in self.clusters["clusters"] if c["cluster_id"] == cluster_id]
        if not match:
            return None
        conds = self.query(
            """SELECT condition_id, name, modern_equivalent, body_system, dosha, namc_code
               FROM dim_condition WHERE primary_cluster = ? ORDER BY n_symptoms DESC LIMIT ?""",
            [cluster_id, limit],
        )
        enrich = next(
            (e for e in self.clusters["dosha_enrichment"] if e["primary_cluster"] == cluster_id),
            None,
        )
        return {
            **match[0],
            "example_conditions": conds.to_dict("records"),
            "dosha_enrichment": enrich,
        }

    def screen_next(
        self, answers: dict[str, bool], max_questions: int = 12, confidence: float = 0.8
    ) -> dict:
        sc = self.screener
        unknown = sorted(set(answers) - set(sc.symptoms))
        known = {k: v for k, v in answers.items() if k in sc.symptoms}
        top = sc.top_systems(known)
        done = len(known) >= max_questions or top[0][1] >= confidence
        question, gain = (None, 0.0) if done else sc.next_question(known)
        matches = self.match_conditions(known)
        return {
            "next_question": question,
            "expected_information_gain_bits": round(gain, 4),
            "done": done or question is None,
            "top_body_systems": [{"body_system": s, "probability": round(p, 4)} for s, p in top],
            "matching_conditions": matches[
                ["condition_id", "name", "modern_equivalent", "body_system", "namc_code"]
            ].to_dict("records"),
            "ignored_unknown_symptoms": unknown,
        }

    @cached_property
    def _idf(self) -> dict[str, float]:
        n = len(self.condition_profiles)
        df = self.condition_profiles["symptoms"].explode().value_counts()
        return (np.log((1 + n) / (1 + df)) + 1).to_dict()

    def match_conditions(self, answers: dict[str, bool], limit: int = 5) -> pd.DataFrame:
        """Rank conditions by IDF-weighted agreement with the answers.

        Rare symptoms count more than ubiquitous ones (fever); dividing by sqrt(profile
        size) stops long profiles winning just by listing everything.
        """
        prof = self.condition_profiles
        positives = {k for k, v in answers.items() if v}
        if not positives:
            return prof.head(0)
        negatives = set(answers) - positives
        idf = self._idf

        def score(symptoms) -> float:
            s = set(symptoms)
            hit = sum(idf.get(t, 1.0) for t in positives & s)
            miss = sum(idf.get(t, 1.0) for t in negatives & s)
            return (hit - 0.5 * miss) / np.sqrt(len(s))

        ranked = prof.assign(score=prof["symptoms"].map(score)).query("score > 0")
        ranked = ranked.sort_values("score", ascending=False)
        return ranked[~ranked["name"].str.casefold().duplicated()].head(limit)

    def score_risk(self, patient: dict) -> dict:
        model = self.risk_model
        row = pd.DataFrame([patient])
        p = float(model.predict_proba(row)[0])
        return {
            "probability": round(p, 4),
            "flag_for_screening": p >= model.threshold,
            "threshold": round(model.threshold, 4),
            "reasons": model.explain(row),
            "model": model.card["model"],
            "run_id": self.model_card.get("run_id"),
            "disclaimer": "Screening aid only - confirm with HbA1c or fasting plasma glucose.",
        }


_service: AnalyticsService | None = None


def get_service() -> AnalyticsService:
    global _service
    if _service is None:
        _service = AnalyticsService()
    return _service
