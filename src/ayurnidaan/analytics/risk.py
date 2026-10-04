"""Diabetes-status screening model with a model card and per-patient reason codes.

Protocol (no leakage): the cohort is split once into train/holdout *before* variable
discovery. Features = the confirmed + supported variables found on the training split.
Model choice uses CV on train only; the holdout is touched once, for the final card.

Logistic regression is preferred over gradient boosting unless boosting wins by more
than ``min_auc_gain`` - a clinician can audit a coefficient, not a tree ensemble.

Caveat recorded in the card: the outcome is *existing* self-reported diagnosis in a
cross-sectional survey, so this is a screening/triage aid, not a forecast of future
onset, and lifestyle associations may reflect reverse causation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from .variables import CATEGORICAL

TARGET_SENSITIVITY = 0.80


def _split_types(features: list[str]) -> tuple[list[str], list[str]]:
    cats = [f for f in features if f in CATEGORICAL]
    return cats, [f for f in features if f not in cats]


def prepare(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    out = df[features].copy()
    cats, nums = _split_types(features)
    for c in cats:
        out[c] = out[c].fillna("unknown").astype(str)
    for n in nums:
        out[n] = out[n].astype(float)
    return out


def make_logistic(features: list[str]) -> Pipeline:
    cats, nums = _split_types(features)
    pre = ColumnTransformer(
        [("cat", OneHotEncoder(handle_unknown="ignore"), cats), ("num", StandardScaler(), nums)]
    )
    return Pipeline([("pre", pre), ("clf", LogisticRegression(max_iter=2000, C=1.0))])


def make_boosting(features: list[str]) -> Pipeline:
    cats, nums = _split_types(features)
    pre = ColumnTransformer(
        [
            ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), cats),
            ("num", "passthrough", nums),
        ]
    )
    clf = HistGradientBoostingClassifier(
        max_depth=3,
        learning_rate=0.05,
        max_iter=300,
        categorical_features=list(range(len(cats))),
        random_state=0,
    )
    return Pipeline([("pre", pre), ("clf", clf)])


def bootstrap_auc_ci(
    y: np.ndarray, p: np.ndarray, n: int = 1000, seed: int = 0
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    aucs = []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        if len(np.unique(y[idx])) == 2:
            aucs.append(roc_auc_score(y[idx], p[idx]))
    return float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5))


def calibration_slope_intercept(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    """Logistic recalibration: logit(P(y)) = a + b * logit(p). Ideal a = 0, b = 1."""
    import statsmodels.api as sm

    p = np.clip(p, 1e-6, 1 - 1e-6)
    lp = np.log(p / (1 - p))
    fit = sm.Logit(y, sm.add_constant(lp)).fit(disp=0)
    return float(fit.params[1]), float(fit.params[0])


def threshold_for_sensitivity(y: np.ndarray, p: np.ndarray, target: float) -> float:
    pos = np.sort(p[y == 1])
    # Highest threshold that still flags >= target share of true cases.
    k = int(np.floor((1 - target) * len(pos)))
    return float(pos[k])


def operating_point(y: np.ndarray, p: np.ndarray, thr: float) -> dict[str, float]:
    pred = p >= thr
    tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
    fn, tn = int((~pred & (y == 1)).sum()), int((~pred & (y == 0)).sum())
    return {
        "threshold": thr,
        "sensitivity": tp / max(tp + fn, 1),
        "specificity": tn / max(tn + fp, 1),
        "ppv": tp / max(tp + fp, 1),
        "npv": tn / max(tn + fn, 1),
    }


@dataclass
class RiskModel:
    pipeline: Pipeline
    features: list[str]
    threshold: float
    card: dict
    reference: pd.DataFrame | None = None  # one-row "typical patient" (medians / modes)

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        return self.pipeline.predict_proba(prepare(df, self.features))[:, 1]

    def explain(self, row: pd.DataFrame, top: int = 5) -> list[dict]:
        """Model-agnostic reason codes by occlusion.

        For each variable, swap the patient's value for the typical training value and
        measure the change in log-odds. Positive = this answer raises the patient's risk
        relative to a typical patient. Works for any fitted pipeline (LR or boosting).
        """
        if self.reference is None:
            return []
        x = prepare(row, self.features)
        base = _logit(self.pipeline.predict_proba(x)[:, 1][0])
        variants = pd.concat([x] * len(self.features), ignore_index=True)
        for i, f in enumerate(self.features):
            variants.loc[i, f] = self.reference[f].iloc[0]
        occluded = _logit(self.pipeline.predict_proba(variants)[:, 1])
        contrib = {f: float(base - occluded[i]) for i, f in enumerate(self.features)}
        ranked = sorted(contrib.items(), key=lambda kv: -abs(kv[1]))[:top]
        return [
            {
                "variable": v,
                "log_odds": round(c, 4),
                "direction": "raises risk" if c > 0 else "lowers risk",
                "value": _plain(x[v].iloc[0]),
                "typical_value": _plain(self.reference[v].iloc[0]),
            }
            for v, c in ranked
        ]


def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _plain(v):
    return v.item() if hasattr(v, "item") else v


def reference_row(x: pd.DataFrame) -> pd.DataFrame:
    cats, nums = _split_types(list(x.columns))
    ref = {c: x[c].mode().iloc[0] for c in cats} | {n: float(x[n].median()) for n in nums}
    return pd.DataFrame([ref])[list(x.columns)]


def train(
    train_df: pd.DataFrame,
    holdout_df: pd.DataFrame,
    features: list[str],
    outcome: str = "diabetes",
    seed: int = 42,
    min_auc_gain: float = 0.01,
) -> RiskModel:
    tr = train_df[train_df[outcome].notna()]
    ho = holdout_df[holdout_df[outcome].notna()]
    x_tr, y_tr = prepare(tr, features), tr[outcome].astype(int).to_numpy()
    x_ho, y_ho = prepare(ho, features), ho[outcome].astype(int).to_numpy()

    cv = StratifiedKFold(5, shuffle=True, random_state=seed)
    candidates = {
        "logistic_regression": make_logistic(features),
        "gradient_boosting": make_boosting(features),
    }
    oof = {
        k: cross_val_predict(m, x_tr, y_tr, cv=cv, method="predict_proba")[:, 1]
        for k, m in candidates.items()
    }
    cv_auc = {k: float(roc_auc_score(y_tr, p)) for k, p in oof.items()}
    chosen = (
        "gradient_boosting"
        if cv_auc["gradient_boosting"] - cv_auc["logistic_regression"] > min_auc_gain
        else "logistic_regression"
    )
    thr = threshold_for_sensitivity(y_tr, oof[chosen], TARGET_SENSITIVITY)
    pipe = candidates[chosen].fit(x_tr, y_tr)
    p_ho = pipe.predict_proba(x_ho)[:, 1]
    lo, hi = bootstrap_auc_ci(y_ho, p_ho, seed=seed)
    slope, intercept = calibration_slope_intercept(y_ho, p_ho)

    subgroups = {}
    age_band = np.where(ho["age"].astype(float) < 45, "age<45", "age>=45")
    for name, groups in {"gender": ho["gender"].to_numpy(), "age_band": age_band}.items():
        for g in np.unique(groups):
            m = groups == g
            if len(np.unique(y_ho[m])) == 2:
                subgroups[f"{name}={g}"] = {
                    "n": int(m.sum()),
                    "auc": float(roc_auc_score(y_ho[m], p_ho[m])),
                    **{
                        k: v
                        for k, v in operating_point(y_ho[m], p_ho[m], thr).items()
                        if k in ("sensitivity", "specificity")
                    },
                }

    bins = pd.qcut(p_ho, 10, duplicates="drop")
    reliability = (
        pd.DataFrame({"bin": bins, "p": p_ho, "y": y_ho})
        .groupby("bin", observed=True)
        .agg(mean_predicted=("p", "mean"), observed_rate=("y", "mean"), n=("y", "size"))
        .reset_index(drop=True)
        .round(4)
        .to_dict("records")
    )
    card = {
        "model": chosen,
        "intended_use": "Triage aid flagging intake records for diabetes screening "
        "(HbA1c / fasting glucose). Not a diagnosis.",
        "outcome": "self-reported existing diabetes diagnosis (cross-sectional)",
        "limitations": [
            "Cross-sectional: associations may reflect reverse causation (e.g. diagnosed "
            "patients changing diet or sleep).",
            "Survey cohort from one Kaggle source; no external validation.",
            "'Family history: unknown' carries a large effect - likely a collection "
            "artefact; monitor before relying on it.",
        ],
        "features": features,
        "n_train": len(y_tr),
        "n_holdout": len(y_ho),
        "prevalence_train": float(y_tr.mean()),
        "prevalence_holdout": float(y_ho.mean()),
        "cv_auc": cv_auc,
        "holdout": {
            "auc": float(roc_auc_score(y_ho, p_ho)),
            "auc_ci95": [lo, hi],
            "brier": float(brier_score_loss(y_ho, p_ho)),
            "brier_null": float(brier_score_loss(y_ho, np.full_like(p_ho, y_tr.mean()))),
            "calibration_slope": slope,
            "calibration_intercept": intercept,
            "operating_point": operating_point(y_ho, p_ho, thr),
            "reliability": reliability,
        },
        "subgroups": subgroups,
        "threshold_policy": f"chosen on training OOF predictions for sensitivity >= {TARGET_SENSITIVITY}",
    }
    sens = [g["sensitivity"] for g in subgroups.values()]
    if sens and max(sens) - min(sens) > 0.2:
        worst = min(subgroups, key=lambda k: subgroups[k]["sensitivity"])
        card["limitations"].append(
            f"Sensitivity varies by subgroup ({min(sens):.2f}-{max(sens):.2f}); lowest in "
            f"{worst}. A single threshold under-flags this group - consider group-aware "
            "thresholds or a lower threshold for it before deployment."
        )
    return RiskModel(pipe, features, thr, card, reference_row(x_tr))
