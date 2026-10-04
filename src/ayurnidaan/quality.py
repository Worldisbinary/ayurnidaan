"""Data-quality gate.

Every registered source is audited before anything is loaded. Checks are either
*blocking* (the source is rejected) or advisory (reported, handled downstream).

The two non-obvious checks:

* **Noise features** - for each low-cardinality feature, mutual information with the
  label is compared against a permutation null. Features indistinguishable from
  noise are flagged; a source made mostly of noise is rejected.
* **Excess duplicate rate** - exact duplicates minus the rate expected by chance, so a
  short questionnaire with naturally repeating answer patterns is not rejected.
* **Excess signal-duplicate rate** - duplicates are counted again after dropping noise
  features, minus the rate expected by chance (each column shuffled independently).
  This catches datasets "augmented" by appending random columns to a small set of
  repeated rows: exact-duplicate checks pass, signal-duplicate checks do not.

Noise-feature share is advisory: a lifestyle variable that does not predict the outcome
is a finding for feature selection, not an integrity defect.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .config import QualityGate, Source

PERSON_LEVEL_ROLES = {"patient_cohort", "assessment", "audit_only"}
PII_NAME_PATTERN = re.compile(
    r"(^|_|\s)(name|phone|mobile|email|address|aadhaar|dob)($|_|\s)", re.I
)


@dataclass
class CheckResult:
    check: str
    value: float
    threshold: float | None
    passed: bool
    blocking: bool
    detail: str = ""


@dataclass
class SourceReport:
    source: str
    role: str
    rows: int
    columns: int
    checks: list[CheckResult] = field(default_factory=list)
    noise_features: list[str] = field(default_factory=list)
    pii_columns: list[str] = field(default_factory=list)
    conflicting_entities: list[str] = field(default_factory=list)
    conflicting_rows: list[int] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.blocking)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["passed"] = self.passed
        return d


def _codes(s: pd.Series) -> np.ndarray:
    return pd.factorize(s.astype(str), use_na_sentinel=False)[0]


def mutual_information(x: np.ndarray, y: np.ndarray) -> float:
    """MI in nats between two integer-coded discrete variables."""
    nx, ny = x.max() + 1, y.max() + 1
    joint = np.bincount(x * ny + y, minlength=nx * ny).reshape(nx, ny).astype(float)
    joint /= joint.sum()
    px, py = joint.sum(1, keepdims=True), joint.sum(0, keepdims=True)
    nz = joint > 0
    return float((joint[nz] * np.log(joint[nz] / (px @ py)[nz])).sum())


def permutation_mi_pvalue(
    x: np.ndarray, y: np.ndarray, n_perm: int = 200, rng: np.random.Generator | None = None
) -> tuple[float, float]:
    rng = rng or np.random.default_rng(0)
    observed = mutual_information(x, y)
    null = np.array([mutual_information(x, rng.permutation(y)) for _ in range(n_perm)])
    # +1 smoothing: an observed value above every permutation gives p = 1/(n+1), not 0.
    return observed, (1 + (null >= observed).sum()) / (n_perm + 1)


def candidate_features(df: pd.DataFrame, label: str, max_card: int = 50) -> list[str]:
    return [
        c
        for c in df.columns
        if c != label
        and 1 < df[c].nunique(dropna=True) <= max_card
        and not PII_NAME_PATTERN.search(c)
    ]


def detect_noise_features(
    df: pd.DataFrame, label: str, alpha: float, seed: int = 0
) -> tuple[list[str], list[str]]:
    rng = np.random.default_rng(seed)
    y = _codes(df[label])
    feats = candidate_features(df, label)
    noise = [c for c in feats if permutation_mi_pvalue(_codes(df[c]), y, rng=rng)[1] > alpha]
    return feats, noise


def detect_pii(df: pd.DataFrame) -> list[str]:
    out = []
    for c in df.columns:
        if not PII_NAME_PATTERN.search(str(c)):
            continue
        s = df[c].dropna().astype(str)
        if len(s) and s.nunique() / len(s) > 0.5:  # identifier-like, not a category
            out.append(c)
    return out


_STOP = {
    "of",
    "or",
    "and",
    "in",
    "on",
    "the",
    "a",
    "an",
    "with",
    "to",
    "side",
    "severe",
    "mild",
    "difficulty",
}


def _words(text: object) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", str(text).casefold()) if len(w) > 2 and w not in _STOP}


def conflicting_rows(df: pd.DataFrame, entity: str, text: str) -> list[int]:
    """Positions of rows contradicting every other row for the same entity.

    Word-level overlap tolerates paraphrase ("Convulsions" / "Recurrent seizures ...
    loss of consciousness" share words) but catches copy-paste errors: AyurGenixAI lists
    "Asthma" once as "Pain, swelling, difficulty moving" and "Arthritis" once as
    "Vision loss, difficulty focusing". With two rows we cannot tell which is wrong,
    so both are flagged.
    """
    keys = df[entity].astype(str).str.casefold().str.strip().to_numpy()
    words = [_words(t) for t in df[text]]
    flagged = []
    for key in pd.unique(keys):
        pos = np.where(keys == key)[0]
        if len(pos) < 2:
            continue
        for p in pos:
            if all(not (words[p] & words[o]) for o in pos if o != p):
                flagged.append(int(p))
    return flagged


def chance_duplicate_rate(
    df: pd.DataFrame, label: str | None = None, n_rep: int = 5, seed: int = 0
) -> float:
    """Duplicate rate expected by chance.

    Columns are shuffled independently *within each label class*, which keeps every
    feature's class-conditional distribution (features legitimately co-vary through
    the label) while destroying row identity. A padded dataset of repeated rows keeps
    its duplicates under the real data but loses them under this null.
    """
    rng = np.random.default_rng(seed)
    groups = [df.index] if label is None else list(df.groupby(label, sort=False).groups.values())
    rates = []
    for _ in range(n_rep):
        parts = []
        for idx in groups:
            g = df.loc[idx]
            parts.append(
                pd.DataFrame(
                    {
                        c: g[c].to_numpy() if c == label else rng.permutation(g[c].to_numpy())
                        for c in df.columns
                    }
                )
            )
        rates.append(pd.concat(parts, ignore_index=True).duplicated().mean())
    return float(np.mean(rates))


def audit(df: pd.DataFrame, source: Source, gate: QualityGate, seed: int = 0) -> SourceReport:
    rep = SourceReport(source.name, source.role, len(df), df.shape[1])
    add = rep.checks.append

    # Short questionnaires legitimately repeat answer patterns, so only duplicates in
    # excess of chance count against the source.
    dup = float(df.duplicated().mean())
    label = source.label if source.label in df.columns else None
    dup_excess = dup - chance_duplicate_rate(df, label, seed=seed) if dup > 0 else 0.0
    add(
        CheckResult(
            "excess_duplicate_rate",
            dup_excess,
            gate.max_duplicate_rate,
            dup_excess <= gate.max_duplicate_rate,
            True,
            f"{dup:.1%} exact duplicate rows, {dup - dup_excess:.1%} expected by chance",
        )
    )

    null = float(df.isna().mean().mean())
    add(CheckResult("null_rate", null, gate.max_null_rate, null <= gate.max_null_rate, True))

    rep.pii_columns = detect_pii(df) if source.role in PERSON_LEVEL_ROLES else []
    add(
        CheckResult(
            "pii_columns",
            float(len(rep.pii_columns)),
            0,
            not rep.pii_columns,
            False,
            "scrubbed at transform" if rep.pii_columns else "",
        )
    )

    if source.text_column and source.entity_column:
        uniq = df[source.text_column].nunique() / max(df[source.entity_column].nunique(), 1)
        add(
            CheckResult(
                "text_uniqueness",
                float(uniq),
                gate.min_text_uniqueness,
                uniq >= gate.min_text_uniqueness,
                True,
                f"{df[source.text_column].nunique()} distinct '{source.text_column}' strings for "
                f"{df[source.entity_column].nunique()} distinct '{source.entity_column}'",
            )
        )
        rep.conflicting_rows = conflicting_rows(df, source.entity_column, source.text_column)
        rep.conflicting_entities = sorted(
            df.iloc[rep.conflicting_rows][source.entity_column].astype(str).unique()
        )
        add(
            CheckResult(
                "conflicting_entity_profiles",
                float(len(rep.conflicting_rows)),
                0,
                not rep.conflicting_rows,
                False,
                f"{len(rep.conflicting_rows)} rows across {len(rep.conflicting_entities)} entities "
                "contradict other rows for the same entity; flagged `profile_conflict` and "
                "excluded from condition matching",
            )
        )

    if source.label and source.role in {"assessment", "patient_cohort", "audit_only"}:
        feats, noise = detect_noise_features(df, source.label, gate.noise_feature_alpha, seed)
        rep.noise_features = noise
        if feats:
            share = len(noise) / len(feats)
            add(
                CheckResult(
                    "noise_feature_share",
                    share,
                    gate.max_noise_feature_share,
                    share <= gate.max_noise_feature_share,
                    False,
                    f"{len(noise)}/{len(feats)} features carry no label signal (permutation MI)",
                )
            )
            # Keep high-cardinality columns too (age, free text) so legitimately distinct
            # records are not collapsed just because their low-cardinality answers agree.
            excluded = set(noise) | set(rep.pii_columns)
            signal_cols = [c for c in df.columns if c not in excluded]
            if noise and len(signal_cols) > 1:
                observed = float(df[signal_cols].duplicated().mean())
                expected = chance_duplicate_rate(df[signal_cols], source.label, seed=seed)
                excess = observed - expected
                add(
                    CheckResult(
                        "excess_signal_duplicate_rate",
                        excess,
                        gate.max_duplicate_rate,
                        excess <= gate.max_duplicate_rate,
                        True,
                        f"{observed:.1%} duplicates after removing noise features vs "
                        f"{expected:.1%} expected by chance",
                    )
                )
    return rep
