"""Prakriti (constitution) and Vikriti (current imbalance) estimation.

Prakriti is a stable trait, read from the constitution questionnaire. Vikriti is the
present state, read from the symptoms. Ayurvedic assessment needs both: the same
symptom means something different in a Vata-prakriti person than in a Kapha one, and
an imbalance in one's own prakriti dosha is the commonest (and easiest) presentation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DOSHAS = ("vata", "pitta", "kapha")


def _softmax(z: dict[str, float]) -> dict[str, float]:
    m = max(z.values())
    e = {k: np.exp(v - m) for k, v in z.items()}
    s = sum(e.values())
    return {k: float(v / s) for k, v in e.items()}


@dataclass(frozen=True)
class DoshaProfile:
    shares: dict[str, float]  # sums to 1
    answered: int
    evidence: dict[str, list[tuple[str, float]]]  # dosha -> [(item, contribution)]

    @property
    def dominant(self) -> str:
        """'vata', or 'vata-pitta' when the top two are within 10 points (dual-dosha)."""
        ranked = sorted(self.shares, key=self.shares.get, reverse=True)
        if self.shares[ranked[0]] - self.shares[ranked[1]] < 0.10:
            pair = sorted(ranked[:2], key=DOSHAS.index)
            return "-".join(pair)
        return ranked[0]

    def to_dict(self) -> dict:
        return {
            "shares": {k: round(v, 4) for k, v in self.shares.items()},
            "dominant": self.dominant,
            "answered": self.answered,
            "evidence": {
                d: [{"item": i, "weight": round(w, 3)} for i, w in ev[:5]]
                for d, ev in self.evidence.items()
            },
        }


def prakriti(model: dict, answers: dict[str, str]) -> DoshaProfile | None:
    """Apply the exported multinomial logit to questionnaire answers."""
    z = {c.lower(): float(model["intercept"][c]) for c in model["classes"]}
    evidence: dict[str, list] = {d: [] for d in z}
    answered = 0
    for q in model["questions"]:
        value = answers.get(q["id"])
        opt = next((o for o in q["options"] if o["value"] == value), None)
        if opt is None:
            continue
        answered += 1
        for cls, w in opt["weights"].items():
            z[cls.lower()] += w
            evidence[cls.lower()].append((q["id"], w))
    if answered == 0:
        return None
    for d in evidence:
        evidence[d].sort(key=lambda t: -t[1])
    return DoshaProfile(_softmax(z), answered, evidence)


def vikriti(
    table: dict,
    present: list[str],
    extra: dict[str, float] | None = None,
    extra_items: list[dict] | None = None,
    temperature: float | None = None,
) -> DoshaProfile | None:
    """Current imbalance: per-symptom dosha LLRs plus examination / history evidence
    (``extra``, from ``pariksha.dosha_evidence``), softmax-normalised.

    Symptoms within one presentation are strongly correlated, so naively summing their
    LLRs is overconfident (98 % one dosha from three symptoms). The default temperature
    sqrt(n) treats n correlated findings as worth about sqrt(n) independent ones.
    """
    llr = table["llr"]
    used = [s for s in present if s in llr]
    if not used and not any((extra or {}).values()):
        return None
    n_extra = (
        len(extra_items or []) if extra_items is not None else int(any((extra or {}).values()))
    )
    if temperature is None:
        # every finding - symptom, pariksha sign, upashaya, agni - shares one sqrt(n) budget
        temperature = max(1.0, (len(used) + n_extra) ** 0.5)
    z = {d: float(np.log(table["base_rate"][d])) for d in DOSHAS}
    evidence: dict[str, list] = {d: [] for d in DOSHAS}
    for s in used:
        for d in DOSHAS:
            z[d] += llr[s][d] / temperature
            evidence[d].append((s, llr[s][d]))
    for d, w in (extra or {}).items():
        z[d] += w / temperature
    for item in extra_items or []:
        for d, w in item["llr"].items():
            evidence[d].append((f"{item['source']}:{item['item']}", w))
    for d in evidence:
        evidence[d].sort(key=lambda t: -t[1])
    return DoshaProfile(_softmax(z), len(used), evidence)
