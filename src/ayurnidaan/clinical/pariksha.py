"""Structured Ayurvedic examination and history inputs -> dosha evidence.

* Ashtavidha / Dashavidha pariksha findings (pulse, tongue, stool, urine, voice, touch,
  eyes, build) - entered by the practitioner.
* Upashaya-anupashaya (what aggravates / relieves) and Agni (digestive pattern) -
  answered by the patient.
* Ama (undigested metabolic residue) - inferred from its classical signs.

Weights are the classical guna correspondences expressed as log-likelihood ratios set
by hand (0.5 = mild, 0.8 = clear, 1.2 = pathognomonic in the texts); they are *not*
learned and are listed here so a practitioner can audit and adjust them.
"""

from __future__ import annotations

EXAMINATION = {  # field -> option -> {dosha: llr}
    "nadi": {
        "sarpa_vata": {"vata": 1.2},
        "manduka_pitta": {"pitta": 1.2},
        "hamsa_kapha": {"kapha": 1.2},
    },
    "jihva": {
        "dry_cracked": {"vata": 0.8},
        "red_inflamed": {"pitta": 0.8},
        "coated_white": {"kapha": 0.8},
        "normal": {},
    },
    "mala": {
        "hard_dry": {"vata": 0.8},
        "loose_burning": {"pitta": 0.8},
        "sticky_heavy": {"kapha": 0.8},
        "normal": {},
    },
    "mutra": {
        "scanty_clear": {"vata": 0.5},
        "dark_yellow_burning": {"pitta": 0.8},
        "cloudy_turbid": {"kapha": 0.5},
        "normal": {},
    },
    "shabda": {
        "hoarse_dry": {"vata": 0.5},
        "sharp_loud": {"pitta": 0.5},
        "deep_slow": {"kapha": 0.5},
    },
    "sparsha": {"cold_dry": {"vata": 0.8}, "warm": {"pitta": 0.8}, "cool_moist": {"kapha": 0.8}},
    "drik": {
        "dry_dull": {"vata": 0.5},
        "red_yellowish": {"pitta": 0.8},
        "watery_white": {"kapha": 0.5},
    },
    "akriti": {"thin": {"vata": 0.5}, "medium": {"pitta": 0.3}, "heavy": {"kapha": 0.5}},
}

AGGRAVATING = {  # anupashaya: what makes it worse
    "cold": {"vata": 0.5, "kapha": 0.3},
    "wind_dryness": {"vata": 0.8},
    "heat_sun": {"pitta": 0.8},
    "spicy_sour_food": {"pitta": 0.8},
    "damp_weather": {"kapha": 0.8},
    "heavy_sweet_food": {"kapha": 0.8},
    "fasting_irregular_meals": {"vata": 0.8},
    "stress_overwork": {"vata": 0.5, "pitta": 0.3},
    "morning": {"kapha": 0.3},
    "afternoon_noon": {"pitta": 0.3},
    "evening_dawn": {"vata": 0.3},
}
RELIEVING = {  # upashaya: what makes it better
    "warmth": {"vata": 0.5, "kapha": 0.3},
    "oil_massage": {"vata": 0.8},
    "cool_things": {"pitta": 0.8},
    "fasting_light_food": {"kapha": 0.8},
    "exercise": {"kapha": 0.5},
    "rest": {"vata": 0.3},
}
AGNI = {  # digestive pattern -> (agni type, dosha llr)
    "irregular": ("vishama", {"vata": 0.8}),
    "sharp_frequent_hunger": ("tikshna", {"pitta": 0.8}),
    "slow_heavy_after_meals": ("manda", {"kapha": 0.8}),
    "balanced": ("sama", {}),
}
AMA_SIGNS = (
    "coated tongue",
    "heaviness",
    "tastelessness",
    "loss of appetite",
    "indigestion",
    "bloating",
    "fatigue",
    "slow digestion",
)


def dosha_evidence(
    examination: dict[str, str] | None = None,
    aggravating: list[str] | None = None,
    relieving: list[str] | None = None,
    agni: str | None = None,
) -> tuple[dict[str, float], list[dict]]:
    """Summed dosha LLRs and an itemised trail of where each came from."""
    total = {"vata": 0.0, "pitta": 0.0, "kapha": 0.0}
    trail = []

    def add(source: str, item: str, llrs: dict[str, float]) -> None:
        for d, w in llrs.items():
            total[d] += w
        if llrs:
            trail.append({"source": source, "item": item, "llr": llrs})

    for f, v in (examination or {}).items():
        add(f"pariksha.{f}", v, EXAMINATION.get(f, {}).get(v, {}))
    for a in aggravating or []:
        add("anupashaya", a, AGGRAVATING.get(a, {}))
    for r in relieving or []:
        add("upashaya", r, RELIEVING.get(r, {}))
    if agni in AGNI:
        add("agni", agni, AGNI[agni][1])
    return total, trail


def ama_assessment(present: set[str], examination: dict[str, str] | None = None) -> dict:
    signs = sorted(s for s in AMA_SIGNS if s in present)
    if (examination or {}).get("jihva") == "coated_white":
        signs.append("coated tongue (examined)")
    level = "high" if len(signs) >= 3 else "moderate" if len(signs) == 2 else "low"
    return {"level": level, "signs": signs}
