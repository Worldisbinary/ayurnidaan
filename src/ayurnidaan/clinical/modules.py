"""Optional assessment modules (questionnaires) and daily tracking rules.

The core intake stays minimal; every module here is optional and raises the profile's
"assessment completeness". Each module is *data* (questions + options with the dosha /
guna signal each answer carries) plus a scorer, so the app renders all of them with one
generic screen and a practitioner can audit every weight in one place.

Signals are classical correspondences set by hand (0.5 mild, 0.8 clear), like
pariksha.py - not learned. Manas Prakriti is a screening aid derived from CS Sharira 4
descriptions, not a validated psychological instrument.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

DOSHAS = ("vata", "pitta", "kapha")
GUNAS = ("sattva", "rajas", "tamas")


@dataclass(frozen=True)
class Option:
    value: str
    label: str
    signals: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    options: tuple[Option, ...] = ()
    kind: str = "single"  # single | number
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None

    def to_dict(self) -> dict:
        d = {"id": self.id, "text": self.text, "kind": self.kind}
        if self.kind == "single":
            d["options"] = [{"value": o.value, "label": o.label} for o in self.options]
        else:
            d.update(unit=self.unit, min=self.minimum, max=self.maximum)
        return d


@dataclass(frozen=True)
class Module:
    id: str
    title: str
    description: str
    questions: tuple[Question, ...]
    scorer: Callable[[Module, dict], dict]
    sex: str | None = None  # restrict to one sex (artava)
    weight: int = 10  # contribution to assessment completeness

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "sex": self.sex,
            "questions": [q.to_dict() for q in self.questions],
        }

    def validate(self, answers: dict) -> dict:
        clean = {}
        for q in self.questions:
            v = answers.get(q.id)
            if v is None or v == "":
                continue
            if q.kind == "number":
                v = float(v)
                if (q.minimum is not None and v < q.minimum) or (
                    q.maximum is not None and v > q.maximum
                ):
                    raise ValueError(f"{q.id} out of range")
            elif v not in {o.value for o in q.options}:
                raise ValueError(f"{q.id}: unknown option {v!r}")
            clean[q.id] = v
        if not clean:
            raise ValueError("no recognised answers")
        return clean

    def score(self, answers: dict) -> dict:
        clean = self.validate(answers)
        result = self.scorer(self, clean)
        result["answered"] = len(clean)
        result["total"] = len(self.questions)
        return result


def _q(qid: str, text: str, *opts: tuple[str, str, dict]) -> Question:
    return Question(qid, text, tuple(Option(v, label, sig) for v, label, sig in opts))


def _signals(module: Module, answers: dict, keys=DOSHAS) -> dict[str, float]:
    total = dict.fromkeys(keys, 0.0)
    for q in module.questions:
        if q.kind != "single" or q.id not in answers:
            continue
        opt = next(o for o in q.options if o.value == answers[q.id])
        for k, w in opt.signals.items():
            if k in total:
                total[k] += w
    return total


def _shares(signals: dict[str, float]) -> dict[str, float]:
    s = sum(signals.values())
    n = len(signals)
    return {k: round(v / s, 3) if s else round(1 / n, 3) for k, v in signals.items()}


# --- 1. Agni, Koshtha, Mala ------------------------------------------------------------------
def _score_digestion(m: Module, a: dict) -> dict:
    sig = _signals(m, a)
    agni = {"irregular": "vishama", "sharp": "tikshna", "slow": "manda", "balanced": "sama"}.get(
        a.get("agni")
    )
    koshtha = {"hard": "krura", "regular": "madhya", "loose": "mridu"}.get(a.get("koshtha"))
    capacity = {"small": "avara", "moderate": "madhyama", "large": "pravara"}.get(
        a.get("aharashakti")
    )
    return {
        "agni": agni,
        "koshtha": koshtha,
        "aharashakti": capacity,
        "mala": {k: a.get(k) for k in ("stool", "urine", "sweat")},
        "dosha_signals": sig,
    }


DIGESTION = Module(
    "agni_mala",
    "Digestion & elimination (Agni · Koshtha · Mala)",
    "How you digest and eliminate - central to every Ayurvedic assessment.",
    (
        _q(
            "agni",
            "Your hunger pattern",
            ("irregular", "Irregular - sometimes hungry, sometimes not", {"vata": 0.8}),
            ("sharp", "Sharp - irritable if I miss a meal", {"pitta": 0.8}),
            ("slow", "Slow - rarely hungry, heavy after meals", {"kapha": 0.8}),
            ("balanced", "Balanced and regular", {}),
        ),
        _q(
            "koshtha",
            "Your bowels usually are",
            ("hard", "Hard / irregular, often constipated", {"vata": 0.8}),
            ("regular", "Regular, well-formed", {"kapha": 0.3}),
            ("loose", "Soft, move easily, sometimes loose", {"pitta": 0.8}),
        ),
        _q(
            "stool",
            "Stool in the last 2 weeks",
            ("hard_dry", "Hard, dry, pellet-like", {"vata": 0.8}),
            ("loose_burning", "Loose, yellowish or burning", {"pitta": 0.8}),
            ("sticky_heavy", "Sticky, heavy, with mucus", {"kapha": 0.8}),
            ("normal", "Normal", {}),
        ),
        _q(
            "urine",
            "Urine",
            ("scanty_clear", "Scanty, clear", {"vata": 0.5}),
            ("dark_yellow_burning", "Dark yellow or burning", {"pitta": 0.8}),
            ("cloudy_turbid", "Cloudy / frothy", {"kapha": 0.5}),
            ("normal", "Normal", {}),
        ),
        _q(
            "sweat",
            "Sweating",
            ("scanty", "Very little, skin stays dry", {"vata": 0.5}),
            ("profuse", "Profuse, strong smell, feel hot", {"pitta": 0.8}),
            ("moderate_cool", "Moderate, cool and sticky", {"kapha": 0.5}),
            ("normal", "Normal", {}),
        ),
        _q(
            "aharashakti",
            "How much can you eat and digest comfortably?",
            ("small", "Small amounts only", {"vata": 0.3}),
            ("moderate", "Moderate", {}),
            ("large", "Large meals easily", {"pitta": 0.3}),
        ),
    ),
    _score_digestion,
    weight=15,
)


# --- 2. Ojas / Bala (strength, immunity) -----------------------------------------------------
_OJAS_POINTS = {
    "energy": {"steady": 20, "dips": 10, "exhausted": 0},
    "recovery": {"quick": 20, "average": 12, "slow": 0},
    "infections": {"rare": 20, "some": 10, "frequent": 0},
    "sleep": {"refreshing": 15, "light": 5, "heavy": 7},
    "stress": {"calm": 15, "irritable": 7, "overwhelmed": 0},
    "vyayamashakti": {"high": 10, "moderate": 6, "low": 0},
}


def _score_ojas(m: Module, a: dict) -> dict:
    got = sum(_OJAS_POINTS[k][v] for k, v in a.items() if k in _OJAS_POINTS)
    possible = sum(max(_OJAS_POINTS[k].values()) for k in a if k in _OJAS_POINTS)
    score = round(100 * got / possible) if possible else None
    level = (
        None
        if score is None
        else "pravara"
        if score >= 70
        else "madhyama"
        if score >= 40
        else "avara"
    )
    return {
        "ojas_score": score,
        "bala": level,
        "vyayamashakti": a.get("vyayamashakti"),
        "dosha_signals": _signals(m, a),
    }


OJAS = Module(
    "ojas_bala",
    "Strength & immunity (Ojas · Bala)",
    "Ojas is the essence of all tissues - resilience, immunity and vitality.",
    (
        _q(
            "energy",
            "Energy through the day",
            ("steady", "Steady all day", {}),
            ("dips", "Comes and goes", {"vata": 0.5}),
            ("exhausted", "Tired most of the time", {"vata": 0.5, "kapha": 0.3}),
        ),
        _q(
            "recovery",
            "After an illness you recover",
            ("quick", "Quickly", {}),
            ("average", "In the usual time", {}),
            ("slow", "Slowly", {"vata": 0.5}),
        ),
        _q(
            "infections",
            "Colds, fevers or infections per year",
            ("rare", "0-1", {}),
            ("some", "2-3", {}),
            ("frequent", "4 or more", {"kapha": 0.5}),
        ),
        _q(
            "sleep",
            "Your sleep",
            ("refreshing", "Deep and refreshing", {}),
            ("light", "Light, interrupted", {"vata": 0.8}),
            ("heavy", "Long and heavy, hard to wake", {"kapha": 0.8}),
        ),
        _q(
            "stress",
            "Under stress you become",
            ("calm", "Calm, steady", {}),
            ("irritable", "Irritable, angry", {"pitta": 0.8}),
            ("overwhelmed", "Anxious, overwhelmed", {"vata": 0.8}),
        ),
        _q(
            "vyayamashakti",
            "Exercise capacity (Vyayamashakti)",
            ("high", "High - exercise hard without tiring", {}),
            ("moderate", "Moderate", {}),
            ("low", "Low - tire quickly", {"vata": 0.3}),
        ),
    ),
    _score_ojas,
    weight=15,
)


# --- 3. Manas Prakriti (Sattva / Rajas / Tamas) - CS Sharira 4.36-40 descriptions ------------
def _g(qid: str, text: str, sattva: str, rajas: str, tamas: str) -> Question:
    return _q(
        qid,
        text,
        ("s", sattva, {"sattva": 1}),
        ("r", rajas, {"rajas": 1}),
        ("t", tamas, {"tamas": 1}),
    )


def _score_manas(m: Module, a: dict) -> dict:
    sig = _signals(m, a, GUNAS)
    shares = _shares(sig)
    return {
        "guna_shares": shares,
        "dominant": max(shares, key=shares.get),
        "note": "Screening aid from classical descriptions; not a psychological assessment.",
    }


MANAS = Module(
    "manas_prakriti",
    "Mental constitution (Manas Prakriti)",
    "Sattva (clarity), Rajas (activity) and Tamas (inertia) - the mind's qualities.",
    (
        _g(
            "criticism",
            "When criticised you",
            "reflect on it calmly",
            "argue back",
            "withdraw or ignore it",
        ),
        _g(
            "drive",
            "Your usual drive",
            "purposeful and balanced",
            "restless, ambitious",
            "low, put things off",
        ),
        _g(
            "food",
            "You prefer food that is",
            "fresh and light",
            "spicy and stimulating",
            "heavy, leftover or fried",
        ),
        _g("decisions", "Decisions", "clear and considered", "quick, impulsive", "hard to make"),
        _g(
            "emotions",
            "Emotionally you are mostly",
            "content, compassionate",
            "passionate, quick to anger",
            "dull or stuck",
        ),
        _g("learning", "Learning and memory", "clear, retains well", "quick but scattered", "slow"),
        _g("speech", "Your speech", "truthful and measured", "forceful, a lot", "little, unclear"),
        _g("work", "At work you are", "steady and devoted", "competitive", "procrastinating"),
        _g(
            "free_time",
            "Free time goes to",
            "reading, reflection, service",
            "socialising, activity",
            "sleeping, idle screen time",
        ),
        _g(
            "conflict",
            "In a conflict you",
            "seek a fair resolution",
            "want to win",
            "avoid it entirely",
        ),
    ),
    _score_manas,
    weight=10,
)


# --- 4. Dashavidha pariksha items a patient can answer ---------------------------------------
def _score_dashavidha(m: Module, a: dict) -> dict:
    bmi = None
    if a.get("height_cm") and a.get("weight_kg"):
        bmi = round(a["weight_kg"] / (a["height_cm"] / 100) ** 2, 1)
    # WHO Asian cut-offs (Lancet 2004): 23 overweight, 25 obese
    pramana = (
        None
        if bmi is None
        else "underweight"
        if bmi < 18.5
        else "normal"
        if bmi < 23
        else "overweight"
        if bmi < 25
        else "obese"
    )
    return {
        "bmi": bmi,
        "pramana": pramana,
        "samhanana": a.get("samhanana"),
        "satmya": a.get("satmya"),
        "dosha_signals": _signals(m, a),
    }


DASHAVIDHA = Module(
    "dashavidha",
    "Body measures (Dashavidha pariksha)",
    "Pramana (body measure), Samhanana (compactness) and Satmya (adaptability).",
    (
        Question("height_cm", "Height", kind="number", unit="cm", minimum=50, maximum=230),
        Question("weight_kg", "Weight", kind="number", unit="kg", minimum=10, maximum=250),
        _q(
            "samhanana",
            "Your body build feels",
            ("firm", "Firm, well-knit", {"kapha": 0.3}),
            ("moderate", "Moderate", {}),
            ("loose", "Loose, slight", {"vata": 0.3}),
        ),
        _q(
            "satmya",
            "You adapt to new foods and climates",
            ("all", "Easily - most suit me", {}),
            ("some", "Some suit me", {}),
            ("few", "With difficulty - few suit me", {"vata": 0.3}),
        ),
    ),
    _score_dashavidha,
    weight=10,
)


# --- 5. Artava (menstrual health) -------------------------------------------------------------
def _score_artava(m: Module, a: dict) -> dict:
    sig = _signals(m, a)
    return {
        "dosha_signals": sig,
        "pattern": max(sig, key=sig.get) if any(sig.values()) else "balanced",
    }


ARTAVA = Module(
    "artava",
    "Menstrual health (Artava)",
    "Cycle pattern reflects Apana Vata, Pitta heat and Kapha heaviness.",
    (
        _q(
            "regularity",
            "Your cycle is",
            ("regular", "Regular", {}),
            ("irregular", "Irregular", {"vata": 0.8}),
            ("na", "Not applicable (pregnant, menopausal)", {}),
        ),
        _q(
            "length",
            "Cycle length",
            ("short", "Shorter than 24 days", {"pitta": 0.5}),
            ("normal", "24-35 days", {}),
            ("long", "Longer than 35 days", {"kapha": 0.5, "vata": 0.3}),
        ),
        _q(
            "flow",
            "Flow",
            ("scanty", "Scanty", {"vata": 0.8}),
            ("heavy", "Heavy", {"pitta": 0.8}),
            ("moderate", "Moderate", {}),
        ),
        _q(
            "pain",
            "Pain",
            ("cramping", "Severe cramping", {"vata": 0.8}),
            ("burning", "Burning, with heat or irritability", {"pitta": 0.8}),
            ("dull", "Dull, heavy, bloated", {"kapha": 0.8}),
            ("none", "Little or none", {}),
        ),
        _q(
            "character",
            "Blood is mostly",
            ("dark_clots", "Dark with small clots", {"vata": 0.5}),
            ("bright", "Bright red", {"pitta": 0.5}),
            ("mucoid", "Pale or mucoid", {"kapha": 0.5}),
            ("normal", "Normal", {}),
        ),
    ),
    _score_artava,
    sex="female",
    weight=10,
)


def _prakriti_module(pack_model: dict | None, mid: str, title: str, weight: int) -> Module | None:
    """Wrap a knowledge-pack Prakriti model (quick 9-item or full 25-item) as a module."""
    if not pack_model:
        return None
    from .dosha import prakriti

    questions = tuple(
        Question(
            q["id"], q["question"], tuple(Option(o["value"], o["value"]) for o in q["options"])
        )
        for q in pack_model["questions"]
    )

    def score(m: Module, a: dict) -> dict:
        prof = prakriti(pack_model, a)
        return prof.to_dict() if prof else {}

    return Module(
        mid,
        title,
        f"{len(questions)} questions about your lifelong body-mind traits.",
        questions,
        score,
        weight=weight,
    )


def registry(pack) -> dict[str, Module]:
    mods = [
        DIGESTION,
        OJAS,
        MANAS,
        DASHAVIDHA,
        ARTAVA,
        _prakriti_module(pack.prakriti, "prakriti_quick", "Prakriti - quick (9 questions)", 20),
        _prakriti_module(
            getattr(pack, "prakriti_full", None),
            "prakriti_full",
            "Prakriti - full questionnaire (25 questions)",
            0,
        ),
    ]
    return {m.id: m for m in mods if m is not None}


# =============================================================================================
# Daily tracking: Dinacharya + diet (Viruddha ahara, six tastes)
# =============================================================================================
DINACHARYA = {  # item -> (label, points)
    "woke_before_6": ("Woke before 6 am (Brahma muhurta)", 15),
    "slept_7_8": ("Slept 7-8 hours", 15),
    "meals_on_time": ("Meals at regular times, main meal at midday", 15),
    "exercise_30": ("Exercise or yoga for 30+ minutes", 15),
    "abhyanga": ("Oil massage (Abhyanga)", 10),
    "pranayama": ("Meditation or pranayama", 10),
    "warm_water": ("Drank warm water through the day", 10),
    "no_screens_late": ("No screens after 10 pm", 10),
}

RASA_EFFECT = {  # six tastes -> dosha effect (CS Sutra 26.43): -1 pacifies, +1 aggravates
    "sweet": {"vata": -1, "pitta": -1, "kapha": 1},
    "sour": {"vata": -1, "pitta": 1, "kapha": 1},
    "salty": {"vata": -1, "pitta": 1, "kapha": 1},
    "pungent": {"vata": 1, "pitta": 1, "kapha": -1},
    "bitter": {"vata": 1, "pitta": -1, "kapha": -1},
    "astringent": {"vata": 1, "pitta": -1, "kapha": -1},
}

FOODS = {  # food -> (label, tastes, tags)
    "milk": ("Milk", ("sweet",), ("milk",)),
    "curd": ("Curd / yogurt", ("sour",), ("curd",)),
    "buttermilk": ("Buttermilk (takra)", ("sour", "astringent"), ()),
    "ghee": ("Ghee", ("sweet",), ("ghee",)),
    "honey": ("Honey", ("sweet", "astringent"), ("honey",)),
    "hot_drink": ("Tea / coffee / hot drink", ("bitter", "astringent"), ("hot",)),
    "fish": ("Fish", ("sweet",), ("fish",)),
    "meat": ("Meat", ("sweet",), ("meat",)),
    "eggs": ("Eggs", ("sweet",), ("meat",)),
    "sour_fruit": ("Citrus / sour fruit", ("sour",), ("sour_fruit",)),
    "banana": ("Banana", ("sweet", "astringent"), ("banana",)),
    "other_fruit": ("Other fruit", ("sweet",), ()),
    "radish": ("Radish", ("pungent",), ("radish",)),
    "salty_snack": ("Salty snacks / namkeen", ("salty",), ("salty",)),
    "fried": ("Fried food", ("salty",), ("heavy",)),
    "sweets": ("Sweets / desserts", ("sweet",), ("heavy",)),
    "spicy": ("Spicy food", ("pungent",), ()),
    "greens": ("Leafy greens", ("bitter", "astringent"), ()),
    "dal": ("Dal / lentils", ("astringent", "sweet"), ()),
    "rice": ("Rice", ("sweet",), ()),
    "roti": ("Roti / wheat", ("sweet",), ()),
    "cold_drink": ("Cold drink / ice cream", ("sweet",), ("cold",)),
    "fermented": ("Idli / dosa / fermented", ("sour",), ()),
    "alcohol": ("Alcohol", ("sour", "pungent"), ()),
    "leftovers": ("Leftover / stale food", (), ("stale",)),
}

# Viruddha ahara - incompatible combinations (CS Sutra 26.81-101). (tags, meal or None, message)
VIRUDDHA = [
    (
        {"milk", "fish"},
        None,
        "Milk with fish is a classical incompatible combination (Samyoga viruddha).",
    ),
    (
        {"milk", "sour_fruit"},
        None,
        "Milk with sour fruit curdles in the stomach (Samyoga viruddha).",
    ),
    ({"milk", "salty"}, None, "Milk with salty food is considered incompatible."),
    ({"milk", "radish"}, None, "Milk with radish is a classical incompatible combination."),
    ({"milk", "banana"}, None, "Milk with banana is heavy and produces Ama."),
    ({"milk", "meat"}, None, "Milk with meat or eggs is considered incompatible."),
    (
        {"honey", "hot"},
        None,
        "Honey should not be heated or taken in hot drinks (Samskara viruddha).",
    ),
    (
        {"honey", "ghee"},
        None,
        "Honey and ghee in equal quantity are incompatible (Matra viruddha).",
    ),
    ({"hot", "cold"}, None, "Hot and cold foods together disturb Agni (Virya viruddha)."),
    ({"curd"}, "dinner", "Curd at night aggravates Kapha and Pitta (Kala viruddha)."),
    ({"stale"}, None, "Stale or reheated food is tamasic and produces Ama."),
]


def dinacharya_score(items: dict[str, bool]) -> int:
    return sum(points for k, (_, points) in DINACHARYA.items() if items.get(k))


def analyse_meals(meals: dict[str, list[str]]) -> dict:
    """meals: {"breakfast": [...], "lunch": [...], "dinner": [...]} of FOODS keys."""
    flags, tastes = [], dict.fromkeys(RASA_EFFECT, 0)
    for meal, foods in meals.items():
        tags = {t for f in foods if f in FOODS for t in FOODS[f][2]}
        for need, when, msg in VIRUDDHA:
            if need <= tags and (when is None or when == meal):
                flags.append({"meal": meal, "message": msg})
        for f in foods:
            for t in FOODS.get(f, ("", (), ()))[1]:
                tastes[t] += 1
    effect = dict.fromkeys(DOSHAS, 0)
    for t, n in tastes.items():
        for d, e in RASA_EFFECT[t].items():
            effect[d] += e * n
    missing = [t for t, n in tastes.items() if n == 0]
    return {"viruddha": flags, "tastes": tastes, "dosha_effect": effect, "missing_tastes": missing}


def catalog() -> dict:
    return {
        "dinacharya": [
            {"id": k, "label": label, "points": p} for k, (label, p) in DINACHARYA.items()
        ],
        "foods": [{"id": k, "label": v[0], "tastes": list(v[1])} for k, v in FOODS.items()],
        "meals": ["breakfast", "lunch", "dinner"],
    }


def today() -> date:
    return date.today()
