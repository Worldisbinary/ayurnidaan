"""Classical Ayurvedic rule tables: subdoshas, dhatus, srotas, vaya, dosha clock, koshtha.

These are *textbook rules*, not learned models - there is no labelled dataset of
subdosha or dhatu diagnoses to learn from. Each table cites its source so a BAMS
practitioner can audit it, and the API labels every output derived from here as
rule-based. Symptoms are the engine's canonical vocabulary (knowledge_pack/symptoms.json).

Sources: Ashtanga Hridaya (AH) Sutrasthana 11-12; Charaka Samhita (CS) Sutrasthana 17,
Vimanasthana 5 and 8.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# --- Subdoshas (AH Sutra 12.4-18): seat, function, signs of vitiation -------------------
SUBDOSHAS: dict[str, dict] = {
    "prana": {
        "dosha": "vata",
        "seat": "head, chest",
        "governs": "breathing, swallowing, mind",
        "signs": [
            "shortness of breath",
            "wheezing",
            "anxiety",
            "insomnia",
            "dizziness",
            "worry",
            "restlessness",
            "difficulty swallowing",
        ],
    },
    "udana": {
        "dosha": "vata",
        "seat": "throat, chest",
        "governs": "speech, effort, memory",
        "signs": [
            "hoarseness",
            "difficulty speaking",
            "muffled voice",
            "memory loss",
            "low energy",
            "cough",
        ],
    },
    "samana": {
        "dosha": "vata",
        "seat": "beside the digestive fire",
        "governs": "movement of food, absorption",
        "signs": ["variable appetite", "malabsorption", "diarrhea", "bloating"],
    },
    "vyana": {
        "dosha": "vata",
        "seat": "heart, whole body",
        "governs": "circulation, movement",
        "signs": [
            "palpitations",
            "irregular heartbeat",
            "tremors",
            "numbness",
            "tingling",
            "muscle spasm",
            "low blood pressure",
            "loss of sensation",
        ],
    },
    "apana": {
        "dosha": "vata",
        "seat": "colon, pelvis",
        "governs": "elimination, menstruation, childbirth",
        "signs": [
            "constipation",
            "gas",
            "lower abdominal pain",
            "irregular periods",
            "difficulty urinating",
            "pelvic pain",
            "back pain",
            "weak stream",
            "difficulty passing stool",
            "straining",
            "tenesmus",
        ],
    },
    "pachaka": {
        "dosha": "pitta",
        "seat": "stomach, small intestine",
        "governs": "digestion",
        "signs": [
            "acidity",
            "regurgitation",
            "burning sensation",
            "indigestion",
            "thirst",
            "diarrhea",
        ],
    },
    "ranjaka": {
        "dosha": "pitta",
        "seat": "liver, spleen",
        "governs": "blood formation",
        "signs": [
            "jaundice",
            "anemia",
            "dark urine",
            "liver enlargement",
            "hepatomegaly",
            "bleeding tendency",
            "pallor",
        ],
    },
    "sadhaka": {
        "dosha": "pitta",
        "seat": "heart (mind)",
        "governs": "emotion, intellect, ambition",
        "signs": ["anger", "irritability", "mood swings", "low mood", "depression", "agitation"],
    },
    "alochaka": {
        "dosha": "pitta",
        "seat": "eyes",
        "governs": "vision",
        "signs": [
            "red eyes",
            "photophobia",
            "eye pain",
            "blurred vision",
            "reduced vision",
            "vision problems",
        ],
    },
    "bhrajaka": {
        "dosha": "pitta",
        "seat": "skin",
        "governs": "complexion, body heat",
        "signs": [
            "rash",
            "redness",
            "photosensitivity",
            "skin lesions",
            "hot flushes",
            "burning pain",
            "heat intolerance",
        ],
    },
    "kledaka": {
        "dosha": "kapha",
        "seat": "stomach",
        "governs": "moistening food",
        "signs": [
            "heaviness",
            "nausea",
            "slow digestion",
            "loss of appetite",
            "coated tongue",
            "salivation",
        ],
    },
    "avalambaka": {
        "dosha": "kapha",
        "seat": "chest, heart, lungs",
        "governs": "support, lubrication of chest",
        "signs": ["chest congestion", "productive cough", "mucus", "wheezing", "lung infections"],
    },
    "bodhaka": {
        "dosha": "kapha",
        "seat": "tongue",
        "governs": "taste",
        "signs": ["loss of taste", "tastelessness", "salivation", "coated tongue"],
    },
    "tarpaka": {
        "dosha": "kapha",
        "seat": "head, sinuses",
        "governs": "nourishing the senses",
        "signs": [
            "nasal congestion",
            "runny nose",
            "sneezing",
            "loss of smell",
            "drowsiness",
            "nasal obstruction",
            "congestion",
        ],
    },
    "shleshaka": {
        "dosha": "kapha",
        "seat": "joints",
        "governs": "joint lubrication",
        "signs": [
            "joint pain",
            "stiffness",
            "swelling",
            "reduced range of motion",
            "muscle stiffness",
        ],
    },
}

# --- Sapta dhatu kshaya (depletion) / vriddhi (excess) signs (CS Sutra 17; AH Sutra 11) --
DHATUS: dict[str, dict] = {
    "rasa": {
        "nourishes": "plasma, lymph",
        "kshaya": ["dryness", "dry mouth", "thirst", "fatigue", "palpitations", "dehydration"],
        "vriddhi": ["nausea", "salivation", "heaviness", "loss of appetite"],
    },
    "rakta": {
        "nourishes": "blood",
        "kshaya": ["pallor", "anemia", "dry skin", "low blood pressure", "cold intolerance"],
        "vriddhi": [
            "rash",
            "redness",
            "skin lesions",
            "abscess",
            "bleeding tendency",
            "jaundice",
            "red eyes",
            "hypertension",
        ],
    },
    "mamsa": {
        "nourishes": "muscle",
        "kshaya": ["emaciation", "muscle wasting", "weight loss", "muscle weakness", "weakness"],
        "vriddhi": ["local swelling", "swollen lymph nodes", "thickening"],
    },
    "meda": {
        "nourishes": "fat",
        "kshaya": ["emaciation", "dry skin", "joint pain"],
        "vriddhi": ["weight gain", "sweating", "foul smell", "thirst", "fatigue"],
    },
    "asthi": {
        "nourishes": "bone, teeth, nails, hair",
        "kshaya": ["bone pain", "fractures", "cracking", "joint pain"],
        "vriddhi": ["skeletal deformities", "thickening"],
    },
    "majja": {
        "nourishes": "marrow, nerves",
        "kshaya": ["dizziness", "blurred vision", "bone pain", "fainting", "memory loss"],
        "vriddhi": ["heaviness", "drowsiness", "numbness"],
    },
    "shukra": {
        "nourishes": "reproductive tissue",
        "kshaya": ["infertility", "low energy", "weakness"],
        "vriddhi": [],
    },
}

# --- Srotas: channels and signs of their vitiation (CS Vimana 5) -----------------------
SROTAS: dict[str, dict] = {
    "pranavaha": {
        "carries": "breath",
        "signs": [
            "cough",
            "shortness of breath",
            "wheezing",
            "chest congestion",
            "chest tightness",
            "hemoptysis",
            "productive cough",
            "lung infections",
        ],
    },
    "udakavaha": {"carries": "water", "signs": ["thirst", "dry mouth", "dehydration"]},
    "annavaha": {
        "carries": "food",
        "signs": [
            "loss of appetite",
            "indigestion",
            "nausea",
            "vomiting",
            "acidity",
            "regurgitation",
            "belching",
            "tastelessness",
            "slow digestion",
        ],
    },
    "rasavaha": {
        "carries": "plasma",
        "signs": ["fever", "fatigue", "heaviness", "tastelessness", "pallor"],
    },
    "raktavaha": {
        "carries": "blood",
        "signs": [
            "skin lesions",
            "rash",
            "abscess",
            "jaundice",
            "bleeding",
            "epistaxis",
            "red eyes",
            "bleeding tendency",
        ],
    },
    "mamsavaha": {
        "carries": "muscle",
        "signs": [
            "muscle pain",
            "muscle wasting",
            "swollen lymph nodes",
            "local swelling",
            "muscle weakness",
        ],
    },
    "medovaha": {"carries": "fat", "signs": ["weight gain", "sweating", "thirst", "foul smell"]},
    "asthivaha": {
        "carries": "bone",
        "signs": ["bone pain", "fractures", "deformity", "cracking", "skeletal deformities"],
    },
    "majjavaha": {
        "carries": "marrow, nerves",
        "signs": [
            "dizziness",
            "fainting",
            "numbness",
            "tingling",
            "memory loss",
            "seizures",
            "confusion",
            "paralysis",
        ],
    },
    "shukravaha": {"carries": "reproductive tissue", "signs": ["infertility"]},
    "mutravaha": {
        "carries": "urine",
        "signs": [
            "burning urination",
            "painful urination",
            "dysuria",
            "urgency",
            "difficulty urinating",
            "hematuria",
            "blood in urine",
            "dark urine",
            "weak stream",
        ],
    },
    "purishavaha": {
        "carries": "faeces",
        "signs": [
            "constipation",
            "diarrhea",
            "blood in stool",
            "tenesmus",
            "straining",
            "gas",
            "difficulty passing stool",
            "abdominal cramps",
        ],
    },
    "swedavaha": {
        "carries": "sweat",
        "signs": ["sweating", "night sweats", "dry skin", "roughness"],
    },
    "artavavaha": {
        "carries": "menstrual blood",
        "signs": ["irregular periods", "pelvic pain", "infertility"],
    },
    "manovaha": {
        "carries": "mind",
        "signs": [
            "anxiety",
            "depression",
            "low mood",
            "mood swings",
            "insomnia",
            "hallucinations",
            "worry",
            "agitation",
            "irritability",
            "anger",
        ],
    },
}

# --- Vaya (CS Vimana 8.122): bala < 30, madhya 30-60, jirna > 60 -------------------------
VAYA = [
    (
        0,
        30,
        "bala",
        "kapha",
        "Growth stage - Kapha naturally predominates; prone to colds, congestion.",
    ),
    (
        30,
        60,
        "madhya",
        "pitta",
        "Middle age - Pitta predominates; watch acidity, inflammation, stress.",
    ),
    (
        60,
        200,
        "jirna",
        "vata",
        "Later life - Vata predominates; joints, sleep, dryness, digestion weaken.",
    ),
]

# --- Dosha clock (AH Sutra 1.8): each dosha governs two 4-hour periods -------------------
DOSHA_CLOCK = [
    ("06:00-10:00", "kapha"),
    ("10:00-14:00", "pitta"),
    ("14:00-18:00", "vata"),
    ("18:00-22:00", "kapha"),
    ("22:00-02:00", "pitta"),
    ("02:00-06:00", "vata"),
]

KOSHTHA = {  # bowel nature (CS Sutra 13.66-68)
    "krura": ("vata", "Hard, irregular bowels; needs strong measures to move."),
    "madhya": ("kapha", "Moderate bowels; regular with ordinary diet."),
    "mridu": ("pitta", "Soft bowels; moves easily, even with milk."),
}


def vaya(age: float | None) -> dict | None:
    if age is None:
        return None
    for lo, hi, stage, dosha, note in VAYA:
        if lo <= age < hi:
            return {"stage": stage, "dosha": dosha, "note": note, "age": int(age)}
    return None


def _score(table: dict[str, dict], key: str, present: set[str]) -> list[dict]:
    out = []
    for name, row in table.items():
        matched = sorted(present & set(row[key]))
        if matched:
            out.append({"name": name, "matched": matched, "score": len(matched)})
    return sorted(out, key=lambda r: (-r["score"], r["name"]))


def subdoshas(present: set[str]) -> list[dict]:
    rows = _score(SUBDOSHAS, "signs", present)
    for r in rows:
        meta = SUBDOSHAS[r["name"]]
        r.update(dosha=meta["dosha"], seat=meta["seat"], governs=meta["governs"])
    return rows


def dhatus(present: set[str], bmi: float | None = None) -> list[dict]:
    """Every dhatu with a state: kshaya, vriddhi, mixed or normal (+ BMI for mamsa/meda)."""
    out = []
    for name, row in DHATUS.items():
        low = sorted(present & set(row["kshaya"]))
        high = sorted(present & set(row["vriddhi"]))
        if bmi is not None and name in ("mamsa", "meda"):
            if bmi < 18.5:
                low.append(f"BMI {bmi:.1f} (underweight)")
            elif bmi >= 25 and name == "meda":
                high.append(f"BMI {bmi:.1f} (obese, Asian cut-off)")
        state = "mixed" if low and high else "kshaya" if low else "vriddhi" if high else "normal"
        out.append(
            {
                "name": name,
                "nourishes": row["nourishes"],
                "state": state,
                "kshaya_signs": low,
                "vriddhi_signs": high,
            }
        )
    return out


def srotas(present: set[str]) -> list[dict]:
    rows = []
    for name, row in SROTAS.items():
        matched = sorted(present & set(row["signs"]))
        rows.append(
            {"name": name, "carries": row["carries"], "involved": bool(matched), "matched": matched}
        )
    return sorted(rows, key=lambda r: (-len(r["matched"]), r["name"]))


def dosha_clock(now_hour: int | None = None) -> dict:
    hour = now_hour if now_hour is not None else datetime.now().hour
    for span, dosha in DOSHA_CLOCK:
        start, end = (int(x[:2]) for x in span.split("-"))
        inside = start <= hour < end if start < end else (hour >= start or hour < end)
        if inside:
            return {
                "current": dosha,
                "span": span,
                "schedule": [{"span": s, "dosha": d} for s, d in DOSHA_CLOCK],
            }
    return {"current": None, "span": None, "schedule": []}


@dataclass(frozen=True)
class Derived:
    subdoshas: list[dict]
    dhatus: list[dict]
    srotas: list[dict]

    def to_dict(self) -> dict:
        return {
            "subdoshas": self.subdoshas,
            "dhatus": self.dhatus,
            "srotas": self.srotas,
            "basis": "rule-based (AH Sutra 11-12, CS Sutra 17, CS Vimana 5)",
        }


def derive(present: list[str] | set[str], bmi: float | None = None) -> Derived:
    p = set(present)
    return Derived(subdoshas(p), dhatus(p, bmi), srotas(p))
