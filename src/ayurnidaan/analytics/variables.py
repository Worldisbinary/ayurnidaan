"""Predictive-variable discovery for the patient cohort (outcome: diabetes status).

A variable is reported as predictive only when independent lines of evidence agree:

1. **Univariate association** - chi-square + bias-corrected Cramér's V (categorical) or
   Mann-Whitney U + rank-biserial r (numeric), Benjamini-Hochberg FDR across all tests.
2. **Adjusted effect** - multivariable logistic regression; each variable's contribution
   is tested by a likelihood-ratio test (drop-one), giving one p-value per variable even
   for multi-level categoricals, plus adjusted odds ratios with 95% CIs.
3. **Stability selection** - L1-penalised logistic regression on 100 half-samples;
   selection probability = share of fits keeping any of the variable's columns
   (Meinshausen & Bühlmann, 2010).
4. **Out-of-sample importance** - permutation importance (AUC drop) of a gradient-boosted
   model on held-out folds, which also captures non-linear effects.

Evidence tiers over the three multivariable lines of evidence
(LRT q < 0.05, stability >= 0.6, permutation-importance 95% interval above 0):

    confirmed      all three agree
    supported      two of three
    not supported  otherwise
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import sklearn
import statsmodels.api as sm
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler

CATEGORICAL = [
    "gender",
    "dosha",
    "diet",
    "meal_timing",
    "sleep_quality",
    "daily_routine",
    "family_history",
]
NUMERIC = ["age", "sleep_hours", "stress_level"]
BINARY = ["exercise"]
# Food-preference flags (pref_sweet, pref_oily, ...) are discovered from the cohort.
# n_food_prefs is their exact sum, so it is excluded to keep the design full-rank.


@dataclass
class VariableReport:
    table: pd.DataFrame
    odds_ratios: pd.DataFrame
    reference_levels: dict[str, str]
    predictive: list[str]  # confirmed tier
    supported: list[str]
    n: int
    prevalence: float
    excluded_rows: int


def cramers_v(table: pd.DataFrame) -> float:
    """Bias-corrected Cramér's V (Bergsma, 2013)."""
    chi2 = stats.chi2_contingency(table, correction=False)[0]
    n = table.to_numpy().sum()
    r, k = table.shape
    phi2 = max(0.0, chi2 / n - (k - 1) * (r - 1) / (n - 1))
    rc, kc = r - (r - 1) ** 2 / (n - 1), k - (k - 1) ** 2 / (n - 1)
    denom = min(kc - 1, rc - 1)
    return float(np.sqrt(phi2 / denom)) if denom > 0 else 0.0


def univariate(df: pd.DataFrame, y: pd.Series, variables: list[str]) -> pd.DataFrame:
    rows = []
    for v in variables:
        col = df[v]
        if v in NUMERIC:
            a, b = col[y == 1].dropna(), col[y == 0].dropna()
            u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
            effect = 1 - 2 * u / (len(a) * len(b))  # rank-biserial; >0 means higher in cases
            rows.append(
                {
                    "variable": v,
                    "test": "mann-whitney",
                    "effect": -effect,
                    "effect_measure": "rank-biserial r",
                    "p_value": p,
                }
            )
        else:
            table = pd.crosstab(col.astype(str), y)
            p = stats.chi2_contingency(table)[1]
            rows.append(
                {
                    "variable": v,
                    "test": "chi-square",
                    "effect": cramers_v(table),
                    "effect_measure": "Cramér's V",
                    "p_value": p,
                }
            )
    out = pd.DataFrame(rows)
    out["q_value"] = stats.false_discovery_control(out["p_value"], method="bh")
    return out


def design_matrix(
    df: pd.DataFrame, variables: list[str]
) -> tuple[pd.DataFrame, dict[str, list[str]], dict[str, str]]:
    """Dummy-coded design (most frequent level = reference), variable -> columns, references."""
    parts, groups, refs = [], {}, {}
    for v in variables:
        if v in CATEGORICAL:
            col = df[v].astype(str)
            ref = col.value_counts().index[0]
            refs[v] = ref
            d = pd.get_dummies(col, prefix=v, dtype=float).drop(columns=f"{v}_{ref}")
            parts.append(d)
            groups[v] = list(d.columns)
        elif v == "age":
            parts.append((df[[v]].astype(float) / 10).rename(columns={v: "age_per_10y"}))
            groups[v] = ["age_per_10y"]
        else:
            parts.append(df[[v]].astype(float))
            groups[v] = [v]
    return pd.concat(parts, axis=1), groups, refs


def adjusted_effects(
    x: pd.DataFrame, y: pd.Series, groups: dict[str, list[str]]
) -> tuple[pd.DataFrame, dict[str, float]]:
    xc = sm.add_constant(x, has_constant="add")
    full = sm.Logit(y, xc).fit(disp=0, maxiter=200)
    ci = full.conf_int()
    ors = (
        pd.DataFrame(
            {
                "term": full.params.index,
                "odds_ratio": np.exp(full.params),
                "ci_low": np.exp(ci[0]),
                "ci_high": np.exp(ci[1]),
                "p_value": full.pvalues,
            }
        )
        .query("term != 'const'")
        .reset_index(drop=True)
    )
    lrt = {}
    for v, cols in groups.items():
        reduced = sm.Logit(y, xc.drop(columns=cols)).fit(disp=0, maxiter=200)
        stat = 2 * (full.llf - reduced.llf)
        lrt[v] = float(stats.chi2.sf(stat, df=len(cols)))
    return ors, lrt


def l1_logistic(c: float) -> LogisticRegression:
    """L1 logistic regression across sklearn versions (``penalty`` deprecated in 1.8)."""
    major, minor = (int(p) for p in sklearn.__version__.split(".")[:2])
    if (major, minor) >= (1, 8):
        return LogisticRegression(l1_ratio=1.0, C=c, solver="liblinear")
    return LogisticRegression(penalty="l1", C=c, solver="liblinear")


def stability_selection(
    x: pd.DataFrame,
    y: pd.Series,
    groups: dict[str, list[str]],
    n_iter: int = 100,
    c: float = 0.05,
    seed: int = 42,
) -> dict[str, float]:
    rng = np.random.default_rng(seed)
    xs = StandardScaler().fit_transform(x)
    hits = dict.fromkeys(groups, 0)
    col_idx = {col: i for i, col in enumerate(x.columns)}
    for _ in range(n_iter):
        sub = rng.choice(len(y), len(y) // 2, replace=False)
        m = l1_logistic(c).fit(xs[sub], y.iloc[sub])
        coef = m.coef_.ravel()
        for v, cols in groups.items():
            if np.any(np.abs(coef[[col_idx[cn] for cn in cols]]) > 1e-8):
                hits[v] += 1
    return {v: h / n_iter for v, h in hits.items()}


def permutation_auc_drop(
    df: pd.DataFrame, y: pd.Series, variables: list[str], seed: int = 42, n_repeats: int = 10
) -> tuple[pd.DataFrame, float]:
    """Permutation importance on held-out folds of a gradient-boosted model."""
    xx = df[variables].copy()
    for v in variables:
        if v in CATEGORICAL:
            xx[v] = xx[v].astype("category")
        else:
            xx[v] = xx[v].astype(float)
    cv = StratifiedKFold(5, shuffle=True, random_state=seed)
    drops, aucs = {v: [] for v in variables}, []
    for tr, te in cv.split(xx, y):
        model = HistGradientBoostingClassifier(
            max_depth=3,
            learning_rate=0.05,
            max_iter=300,
            categorical_features="from_dtype",
            random_state=seed,
        ).fit(xx.iloc[tr], y.iloc[tr])
        aucs.append(roc_auc_score(y.iloc[te], model.predict_proba(xx.iloc[te])[:, 1]))
        res = permutation_importance(
            model,
            xx.iloc[te],
            y.iloc[te],
            scoring="roc_auc",
            n_repeats=n_repeats,
            random_state=seed,
        )
        for v, imp in zip(variables, res.importances, strict=True):
            drops[v].extend(imp.tolist())
    out = pd.DataFrame(
        {
            "variable": variables,
            "perm_auc_drop": [np.mean(drops[v]) for v in variables],
            "perm_ci_low": [np.percentile(drops[v], 2.5) for v in variables],
            "perm_ci_high": [np.percentile(drops[v], 97.5) for v in variables],
        }
    )
    return out, float(np.mean(aucs))


def discover(
    cohort: pd.DataFrame, outcome: str = "diabetes", seed: int = 42
) -> tuple[VariableReport, float]:
    data = cohort[cohort[outcome].notna()].copy()
    excluded = len(cohort) - len(data)
    y = data[outcome].astype(int).reset_index(drop=True)
    data = data.reset_index(drop=True)
    data["dosha"] = data["dosha"].fillna("unknown")
    prefs = sorted(c for c in data.columns if c.startswith("pref_"))
    for b in [*BINARY, *prefs]:
        data[b] = data[b].astype(float)
    variables = CATEGORICAL + NUMERIC + BINARY + prefs

    uni = univariate(data, y, variables)
    x, groups, refs = design_matrix(data, variables)
    ors, lrt = adjusted_effects(x, y, groups)
    stab = stability_selection(x, y, groups, seed=seed)
    perm, hgb_auc = permutation_auc_drop(data, y, variables, seed=seed)

    table = uni.merge(perm, on="variable")
    table["lrt_p"] = table["variable"].map(lrt)
    table["lrt_q"] = stats.false_discovery_control(table["lrt_p"], method="bh")
    table["stability"] = table["variable"].map(stab)
    votes = (
        (table["lrt_q"] < 0.05).astype(int)
        + (table["stability"] >= 0.6).astype(int)
        + (table["perm_ci_low"] > 0).astype(int)
    )
    table["evidence_votes"] = votes
    table["evidence_tier"] = np.select(
        [votes == 3, votes == 2], ["confirmed", "supported"], default="not supported"
    )
    table["predictive"] = votes == 3
    # Consensus rank: mean of ranks across the four lines of evidence.
    ranks = pd.concat(
        [
            table["q_value"].rank(),
            table["lrt_p"].rank(),
            (-table["stability"]).rank(),
            (-table["perm_auc_drop"]).rank(),
        ],
        axis=1,
    )
    table["consensus_rank"] = ranks.mean(1).rank(method="min").astype(int)
    table = table.sort_values("consensus_rank").reset_index(drop=True)

    return VariableReport(
        table=table,
        odds_ratios=ors,
        reference_levels=refs,
        predictive=table.loc[table["evidence_tier"] == "confirmed", "variable"].tolist(),
        supported=table.loc[table["evidence_tier"] == "supported", "variable"].tolist(),
        n=len(y),
        prevalence=float(y.mean()),
        excluded_rows=excluded,
    ), hgb_auc
