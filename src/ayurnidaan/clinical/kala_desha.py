"""Kala (season) and Desha (habitat): the time and place factors of Ayurvedic assessment.

**Ritu (season).** Six two-month seasons of the Indian year (Ashtanga Hridaya, Sutra 3).
Calendar boundaries use the conventional solar-month mapping (mid-month to mid-month).

**Dosha chaya-prakopa-prashama.** Each dosha accumulates (chaya), aggravates (prakopa)
and subsides (prashama) in fixed seasons (Ashtanga Hridaya, Sutra 12):

    Vata  : chaya Grishma  -> prakopa Varsha  -> prashama Sharad
    Pitta : chaya Varsha   -> prakopa Sharad  -> prashama Hemanta
    Kapha : chaya Shishira -> prakopa Vasanta -> prashama Grishma

**Desha (habitat).** Charaka (Vimana 3) describes Jangala (arid, sparse - Vata/Pitta
predominant), Anupa (marshy, humid - Kapha/Vata) and Sadharana (temperate, balanced).
We classify a location from one year of ERA5 reanalysis (Open-Meteo archive):
annual rainfall < 750 mm -> Jangala, > 1500 mm or mean RH > 78 % -> Anupa, else
Sadharana. Thresholds are a documented heuristic (they place Rajasthan in Jangala and
coastal Kerala in Anupa, as the classical descriptions do), not a classical rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

RITUS = ("shishira", "vasanta", "grishma", "varsha", "sharad", "hemanta")
# (month, day) each ritu starts on
_RITU_START = {
    "shishira": (1, 15),
    "vasanta": (3, 15),
    "grishma": (5, 15),
    "varsha": (7, 15),
    "sharad": (9, 15),
    "hemanta": (11, 15),
}
RITU_INFO = {
    "shishira": "Late winter - cold, dry; Kapha accumulates.",
    "vasanta": "Spring - Kapha liquefies and aggravates; digestion weakens.",
    "grishma": "Summer - heat, dryness; Vata accumulates, Kapha subsides.",
    "varsha": "Monsoon - Vata aggravates, Pitta accumulates; digestion weakest.",
    "sharad": "Autumn - Pitta aggravates after the rains.",
    "hemanta": "Early winter - strongest digestion; Pitta subsides.",
}

DOSHA_CYCLE = {  # ritu -> state for each dosha
    "vata": {"grishma": "chaya", "varsha": "prakopa", "sharad": "prashama"},
    "pitta": {"varsha": "chaya", "sharad": "prakopa", "hemanta": "prashama"},
    "kapha": {"shishira": "chaya", "vasanta": "prakopa", "grishma": "prashama"},
}

DESHA_INFO = {
    "jangala": ("Arid, sparse land", ("vata", "pitta")),
    "anupa": ("Marshy, humid land", ("kapha", "vata")),
    "sadharana": ("Temperate, balanced land", ()),
}


def ritu_for(day: date) -> str:
    md = (day.month, day.day)
    current = "hemanta"  # Jan 1-14 is still Hemanta
    for ritu in RITUS:
        if md >= _RITU_START[ritu]:
            current = ritu
    return current


def dosha_states(ritu: str) -> dict[str, str]:
    """{'vata': 'prakopa', 'pitta': 'chaya', 'kapha': 'neutral'} for a ritu."""
    return {d: cycle.get(ritu, "neutral") for d, cycle in DOSHA_CYCLE.items()}


def classify_desha(annual_precip_mm: float, mean_rh: float) -> str:
    if annual_precip_mm > 1500 or mean_rh > 78:
        return "anupa"
    if annual_precip_mm < 750:
        return "jangala"
    return "sadharana"


@dataclass(frozen=True)
class KalaDesha:
    ritu: str
    ritu_info: str
    dosha_states: dict[str, str]
    desha: str | None
    desha_info: str | None
    desha_doshas: tuple[str, ...]

    def seasonal_weight(self, dosha: str) -> float:
        """Multiplicative prior for conditions of a dosha in this season/place.

        Deliberately small: season and habitat shift likelihood, they never decide it.
        """
        w = {"prakopa": 1.20, "chaya": 1.08, "prashama": 0.95, "neutral": 1.0}[
            self.dosha_states[dosha]
        ]
        if dosha in self.desha_doshas:
            w *= 1.05
        return w

    def to_dict(self) -> dict:
        return {
            "ritu": self.ritu,
            "ritu_info": self.ritu_info,
            "dosha_states": self.dosha_states,
            "desha": self.desha,
            "desha_info": self.desha_info,
            "desha_doshas": list(self.desha_doshas),
        }


def kala_desha(day: date, desha: str | None = None) -> KalaDesha:
    ritu = ritu_for(day)
    info, doshas = DESHA_INFO.get(desha, (None, ())) if desha else (None, ())
    return KalaDesha(ritu, RITU_INFO[ritu], dosha_states(ritu), desha, info, tuple(doshas))
