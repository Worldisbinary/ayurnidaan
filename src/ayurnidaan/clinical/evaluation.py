"""Simulated-patient benchmark for the differential engine.

There is no labelled patient dataset with Ayurvedic diagnoses, so the engine is measured
on patients simulated from the knowledge base itself:

* pick a condition (excluding contradictory profiles), an age inside its typical range
  and a sex drawn from its sex weights;
* the patient volunteers ``k`` of the condition's listed symptoms, plus a noise symptom
  with probability ``p_noise`` (patients mention unrelated complaints);
* the adaptive interview then asks ``n_questions`` questions; the simulated patient answers
  "yes" with probability THETA_LISTED for listed symptoms and the background rate otherwise.

A hit is the true condition's *name* in the top-k (duplicate entries of a name across the
two knowledge bases count as the same diagnosis).

Caveat (stated in every report): this measures internal consistency - can the engine
recover a textbook presentation from partial, noisy answers - not accuracy on real
patients. Real-world accuracy can only come from practitioner-confirmed cases, which is
what the feedback loop collects.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from .differential import THETA_LISTED, DifferentialModel
from .dosha import vikriti as vikriti_fn


@dataclass(frozen=True)
class SimConfig:
    volunteered: int = 2
    n_questions: int = 5
    p_noise: float = 0.3
    use_priors: bool = True
    use_dosha: bool = True
    use_demographics: bool = True
    use_prevalence: bool = True


def simulate(model: DifferentialModel, cfg: SimConfig, n: int = 600, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    eligible = [
        i for i, c in enumerate(model.conditions) if len(c["symptoms"]) >= cfg.volunteered + 1
    ]
    picks = rng.choice(eligible, size=min(n, len(eligible)), replace=False)
    terms = np.array(model.terms)
    bg = np.array([s["background"] for s in model.pack.symptoms])
    names = [c["name"].casefold().strip() for c in model.conditions]
    log_prior_backup = model.log_prior
    if not cfg.use_prevalence:
        prev = np.array([c.get("prior_weight", 1.0) for c in model.conditions])
        model.log_prior = model.log_prior - np.log(prev)

    ranks_before, ranks_after = [], []
    try:
        for i in picks:
            c = model.conditions[i]
            profile = [s for s in c["symptoms"] if s in model.t_index]
            answers = {s: True for s in rng.choice(profile, cfg.volunteered, replace=False)}
            if rng.random() < cfg.p_noise:
                noise = rng.choice(terms, p=bg / bg.sum())
                answers.setdefault(str(noise), True)
            lo, hi = c["age"]
            age = float(rng.uniform(lo, min(hi, 90)))
            w = c["sex_weight"]
            sex = "female" if rng.random() < w["female"] / (w["female"] + w["male"]) else "male"

            def rank_of(
                ans: dict[str, bool], c_name: str = names[i], age: float = age, sex: str = sex
            ) -> tuple[int, np.ndarray]:
                present = [s for s, v in ans.items() if v]
                vik = vikriti_fn(model.pack.vikriti, present) if cfg.use_dosha else None
                parts = model.log_scores(
                    ans,
                    age if cfg.use_demographics else None,
                    sex if cfg.use_demographics else None,
                    vik,
                    None,
                    None,
                    use_priors=cfg.use_priors,
                )
                post = model.posterior(parts)
                # Best rank among entries sharing the true name.
                order = np.argsort(-post)
                seen, rank = set(), 0
                for j in order:
                    if names[j] in seen:
                        continue
                    seen.add(names[j])
                    rank += 1
                    if names[j] == c_name:
                        return rank, post
                return rank, post

            r0, post = rank_of(answers)
            ranks_before.append(r0)
            for _ in range(cfg.n_questions):
                q = model.next_questions(post, answers, k=1)
                if not q:
                    break
                s = q[0][0]
                p_yes = THETA_LISTED if s in profile else bg[model.t_index[s]]
                answers[s] = bool(rng.random() < p_yes)
                _, post = rank_of(answers)
            r1, _ = rank_of(answers)
            ranks_after.append(r1)
    finally:
        model.log_prior = log_prior_backup

    def summary(r: list[int]) -> dict:
        a = np.array(r)
        return {
            "top1": float((a <= 1).mean()),
            "top5": float((a <= 5).mean()),
            "top10": float((a <= 10).mean()),
            "mrr": float((1 / a).mean()),
            "median_rank": float(np.median(a)),
        }

    return {
        "n": len(picks),
        "config": cfg.__dict__,
        "volunteered_only": summary(ranks_before),
        "after_interview": summary(ranks_after),
    }


ABLATIONS = {
    "full": SimConfig(),
    "no_dosha": SimConfig(use_dosha=False),
    "no_demographics": SimConfig(use_demographics=False),
    "no_prevalence": SimConfig(use_prevalence=False),
    "symptoms_only": SimConfig(use_priors=False, use_prevalence=False),
}


def run_ablations(model: DifferentialModel, n: int = 600, seed: int = 0) -> dict:
    return {name: simulate(model, cfg, n=n, seed=seed) for name, cfg in ABLATIONS.items()}


__all__ = ["ABLATIONS", "SimConfig", "replace", "run_ablations", "simulate"]
