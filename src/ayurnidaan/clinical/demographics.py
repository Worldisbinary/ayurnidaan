"""Parse free-text 'Age Group' / 'Gender' fields into soft likelihood terms.

The knowledge bases describe who a condition affects in prose ("Adults 30–60",
"Post-menopausal or multiparous women", "Males more common (BPH, stones)"). We turn
that into an age range and a sex weight. Out-of-range ages are *down-weighted*, never
excluded - descriptions are typical, not exhaustive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AgeRange:
    low: int = 0
    high: int = 120

    def likelihood(self, age: float | None) -> float:
        if age is None or self.low <= age <= self.high:
            return 1.0
        gap = (self.low - age) if age < self.low else (age - self.high)
        return max(0.15, 1.0 - gap / 20)  # fades over 20 years, floor 0.15


_AGE_WORDS = [  # (pattern, low, high) - first match wins, order matters
    (r"neonat|from birth|congenital|infant", 0, 2),
    (r"pregnan|post-?partum|lactating|reproductive", 15, 49),
    (r"post-?menopaus", 45, 120),
    (r"child", 0, 18),
    (r"elderly|old age", 60, 120),
    (r"young adult", 18, 35),
    (r"middle-aged", 40, 65),
    (r"adult", 18, 120),
]


def parse_age(text: object) -> AgeRange:
    if not isinstance(text, str) or re.search(r"any age|all age", text, re.I):
        return AgeRange()
    t = text.casefold()
    if m := re.search(r"(\d{1,2})\s*[-–to]+\s*(\d{1,3})", t):
        return AgeRange(int(m.group(1)), int(m.group(2)))
    if m := re.search(r"(\d{1,2})\s*\+", t):
        return AgeRange(int(m.group(1)), 120)
    lows, highs = [], []
    for pat, lo, hi in _AGE_WORDS:
        if re.search(pat, t):
            lows.append(lo)
            highs.append(hi)
    if not lows:
        return AgeRange()
    # "Children and adults" -> union of the ranges mentioned
    return AgeRange(min(lows), max(highs))


@dataclass(frozen=True)
class SexWeight:
    female: float = 1.0
    male: float = 1.0

    def likelihood(self, sex: str | None) -> float:
        if sex == "female":
            return self.female
        if sex == "male":
            return self.male
        return 1.0


_FEMALE = re.compile(r"female|women|woman|pregnan|menopaus|post-?partum|lactat|multiparous|gynae")
_MALE = re.compile(r"(?<![a-z])(?:males?|men)(?![a-z])|prostat")
_LEANING = re.compile(r"more|predominant|mostly|common|slightly|\d+x")


def parse_sex(gender: object, age_text: object = None) -> SexWeight:
    """Exclusive (0.02 for the other sex) only for unambiguous wording; a statement that
    mentions both sexes ("males more in trauma, females in osteoporotic") stays neutral."""
    text = " ".join(str(x) for x in (gender, age_text) if isinstance(x, str)).casefold()
    has_f, has_m = bool(_FEMALE.search(text)), bool(_MALE.search(text))
    if has_f and has_m:
        if re.search(r"females? only|exclusively", text):
            return SexWeight(1.0, 0.02)
        if re.search(r"(?<!fe)males? only", text):
            return SexWeight(0.02, 1.0)
        return SexWeight()
    exclusive_other = 0.6 if (_LEANING.search(text) or "any" in text) else 0.02
    if has_f:
        return SexWeight(1.0, exclusive_other)
    if has_m:
        return SexWeight(exclusive_other, 1.0)
    return SexWeight()
