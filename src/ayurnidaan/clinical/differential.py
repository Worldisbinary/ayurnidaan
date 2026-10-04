"""Ranked differential diagnosis with Ayurvedic priors, explanations and online learning.

Model (per condition c, all terms in log space):

    log P(c | findings) = log prior(c)
                        + sum_{s reported present} log theta[c, s]
                        + sum_{s reported absent}  log (1 - theta[c, s])
                        + log age_fit(c) + log sex_fit(c)
                        + beta  * <vikriti - 1/3, dosha(c)>      (current imbalance agrees)
                        + gamma * <prakriti - 1/3, dosha(c)>     (constitution predisposes)
                        + log seasonal_weight(c)                 (ritu / desha)
                        - const

theta[c, s] = P(symptom s present | condition c). From the knowledge base alone it is
`listed` (0.8) for symptoms in c's profile and a small background rate otherwise.
Practitioner-confirmed cases update it as a Beta posterior (prior strength `m`
pseudo-cases), and the condition prior as a Dirichlet - so the model learns from real
patients while the textbook knowledge stays the prior. Unasked symptoms are
marginalised (no term), so the ranking never assumes an unasked symptom is absent.

The output is a *relative likelihood among known conditions*, not a calibrated
probability of disease; the UI says so.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from .dosha import DOSHAS, DoshaProfile
from .kala_desha import KalaDesha
from .knowledge import KnowledgePack

THETA_LISTED = 0.8
BETA_VIKRITI = 1.0  # chosen by simulated-patient grid search (seed 1), validated on seed 0
GAMMA_PRAKRITI = 0.5


@dataclass
class Feedback:
    """Confirmed cases aggregated into sufficient statistics."""

    condition_counts: dict[str, int] = field(default_factory=dict)
    # (condition_id, symptom) -> [times present, times asked]
    symptom_counts: dict[tuple[str, str], list[int]] = field(default_factory=dict)

    @classmethod
    def from_cases(cls, cases: list[dict]) -> Feedback:
        """cases: [{"condition_id": ..., "answers": {symptom: bool}}]"""
        fb = cls(defaultdict(int), defaultdict(lambda: [0, 0]))
        for case in cases:
            cid = case["condition_id"]
            fb.condition_counts[cid] += 1
            for s, present in case["answers"].items():
                fb.symptom_counts[(cid, s)][1] += 1
                fb.symptom_counts[(cid, s)][0] += int(bool(present))
        return cls(dict(fb.condition_counts), {k: list(v) for k, v in fb.symptom_counts.items()})

    @property
    def n_cases(self) -> int:
        return sum(self.condition_counts.values())


def _entropy_cols(p: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(p > 0, p * np.log2(p), 0.0)
    return -t.sum(0)


class DifferentialModel:
    def __init__(self, pack: KnowledgePack, feedback: Feedback | None = None, m: float = 10.0):
        self.pack = pack
        self.conditions = [c for c in pack.conditions if not c["profile_conflict"]]
        self.terms = [s["term"] for s in pack.symptoms]
        self.t_index = {t: i for i, t in enumerate(self.terms)}
        self.c_index = {c["id"]: i for i, c in enumerate(self.conditions)}
        n_c, n_s = len(self.conditions), len(self.terms)

        bg = np.array([s["background"] for s in pack.symptoms])
        theta = np.tile(bg, (n_c, 1))
        for i, c in enumerate(self.conditions):
            for s in c["symptoms"]:
                if s in self.t_index:
                    theta[i, self.t_index[s]] = THETA_LISTED
        prior_counts = np.ones(n_c)
        self.feedback = feedback or Feedback()
        for (cid, s), (present, asked) in self.feedback.symptom_counts.items():
            if cid in self.c_index and s in self.t_index:
                i, j = self.c_index[cid], self.t_index[s]
                theta[i, j] = (m * theta[i, j] + present) / (m + asked)
        for cid, n in self.feedback.condition_counts.items():
            if cid in self.c_index:
                prior_counts[self.c_index[cid]] += n
        self.theta = np.clip(theta, 1e-4, 1 - 1e-4)
        prevalence = np.array([c.get("prior_weight", 1.0) for c in self.conditions])
        self.log_prior = np.log(prior_counts / prior_counts.sum()) + np.log(prevalence)

        dosha = np.zeros((n_c, 3))
        for i, c in enumerate(self.conditions):
            comps = c["dosha_components"]
            for d in comps:
                dosha[i, DOSHAS.index(d)] = 1 / len(comps)
        self.dosha = dosha
        self.age = np.array([c["age"] for c in self.conditions], dtype=float)
        self.sex = {
            s: np.array([c["sex_weight"][s] for c in self.conditions]) for s in ("female", "male")
        }
        self.n_s = n_s

    # --- scoring ----------------------------------------------------------------------
    def _age_fit(self, age: float | None) -> np.ndarray:
        if age is None:
            return np.ones(len(self.conditions))
        lo, hi = self.age[:, 0], self.age[:, 1]
        gap = np.where(age < lo, lo - age, np.where(age > hi, age - hi, 0.0))
        return np.maximum(0.15, 1 - gap / 20)

    def log_scores(
        self,
        answers: dict[str, bool],
        age: float | None = None,
        sex: str | None = None,
        vikriti: DoshaProfile | None = None,
        prakriti: DoshaProfile | None = None,
        kala_desha: KalaDesha | None = None,
        use_priors: bool = True,
    ) -> dict[str, np.ndarray]:
        parts = {"prior": self.log_prior.copy(), "symptoms": np.zeros(len(self.conditions))}
        for s, present in answers.items():
            j = self.t_index.get(s)
            if j is not None:
                parts["symptoms"] += np.log(self.theta[:, j] if present else 1 - self.theta[:, j])
        if use_priors:
            parts["age"] = np.log(self._age_fit(age))
            parts["sex"] = (
                np.log(self.sex[sex]) if sex in self.sex else np.zeros(len(self.conditions))
            )
            for name, prof, w in (
                ("vikriti", vikriti, BETA_VIKRITI),
                ("prakriti", prakriti, GAMMA_PRAKRITI),
            ):
                if prof is not None:
                    v = np.array([prof.shares[d] for d in DOSHAS]) - 1 / 3
                    parts[name] = w * (self.dosha @ v)
            if kala_desha is not None:
                sw = np.array([kala_desha.seasonal_weight(d) for d in DOSHAS])
                has = self.dosha.sum(1) > 0
                weighted = np.where(
                    has, (self.dosha * sw).sum(1) / np.where(has, self.dosha.sum(1), 1), 1.0
                )
                parts["season"] = np.log(weighted)
        return parts

    def posterior(self, parts: dict[str, np.ndarray]) -> np.ndarray:
        z = sum(parts.values())
        z = z - z.max()
        p = np.exp(z)
        return p / p.sum()

    # --- active questioning ---------------------------------------------------------------
    def next_questions(
        self,
        post: np.ndarray,
        answers: dict[str, bool],
        k: int = 3,
        exclude: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Symptoms with the highest expected entropy reduction over the differential."""
        asked = {self.t_index[s] for s in answers if s in self.t_index}
        asked |= {self.t_index[s] for s in (exclude or ()) if s in self.t_index}
        h0 = _entropy_cols(post[:, None])[0]
        p_yes = post @ self.theta
        post_yes = post[:, None] * self.theta / np.maximum(p_yes, 1e-12)
        post_no = post[:, None] * (1 - self.theta) / np.maximum(1 - p_yes, 1e-12)
        gain = h0 - (p_yes * _entropy_cols(post_yes) + (1 - p_yes) * _entropy_cols(post_no))
        gain[list(asked)] = -np.inf
        top = np.argsort(-gain)[:k]
        return [
            (self.terms[j], float(gain[j])) for j in top if np.isfinite(gain[j]) and gain[j] > 1e-6
        ]

    # --- ranking + explanation ------------------------------------------------------------
    def rank(
        self,
        post: np.ndarray,
        parts: dict[str, np.ndarray],
        answers: dict[str, bool],
        top: int = 10,
    ) -> list[dict]:
        """Top conditions, same-name duplicates merged, each with an evidence breakdown."""
        order = np.argsort(-post)
        seen: dict[str, int] = {}
        out: list[dict] = []
        positives = {s for s, v in answers.items() if v}
        negatives = {s for s, v in answers.items() if not v}
        for i in order:
            c = self.conditions[i]
            key = c["name"].casefold().strip()
            if key in seen:
                # Same disease listed in both knowledge bases: one disease, so take the best
                # entry. Summing would give every duplicated disease double prior mass.
                continue
            if len(out) >= top:
                break
            profile = set(c["symptoms"])
            seen[key] = len(out)
            out.append(
                {
                    "condition_id": c["id"],
                    "name": c["name"],
                    "modern_equivalent": c["modern_equivalent"],
                    "body_system": c["body_system"],
                    "dosha": c["dosha"],
                    "namc": c["namc"],
                    "prognosis": c["prognosis"],
                    "prevalence": c.get("prevalence"),
                    "likelihood": float(post[i]),
                    "evidence": {
                        "supporting": sorted(positives & profile),
                        "reported_absent_but_typical": sorted(negatives & profile),
                        "unexplained": sorted(positives - profile),
                        "typical_not_yet_asked": sorted(profile - set(answers))[:6],
                        "factors": {
                            k: round(float(v[i]), 3) for k, v in parts.items() if k != "symptoms"
                        },
                    },
                }
            )
        return out[:top]
