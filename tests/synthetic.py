"""Schema-faithful synthetic sources with *planted* structure.

CI has no Kaggle credentials, so tests run the full pipeline on these. Because the
signal is planted, tests can assert the algorithms recover it - e.g. symptom clusters
match the planted body systems, and diabetes is driven by age + family history only.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

SYSTEMS = {
    "Respiratory": [
        "cough",
        "wheezing",
        "shortness of breath",
        "chest tightness",
        "sputum",
        "sore throat",
        "sneezing",
        "nasal congestion",
    ],
    "Skin": ["itching", "rash", "scaling", "crusting", "oozing", "redness", "dry skin", "blisters"],
    "Gastrointestinal": [
        "bloating",
        "abdominal pain",
        "nausea",
        "vomiting",
        "diarrhea",
        "constipation",
        "belching",
        "acidity",
    ],
    "Eye": [
        "photophobia",
        "blurred vision",
        "eye pain",
        "lacrimation",
        "dry eyes",
        "itchy eyes",
        "eye discharge",
        "halos",
    ],
    "Musculoskeletal": [
        "joint pain",
        "stiffness",
        "back pain",
        "swelling",
        "reduced mobility",
        "muscle cramps",
        "bone pain",
        "deformity",
    ],
}
DOSHA_BY_SYSTEM = {
    "Respiratory": "Kapha",
    "Skin": "Pitta",
    "Gastrointestinal": "Pitta",
    "Eye": "Pitta/Kapha",
    "Musculoskeletal": "Vata",
}


def patient_intake(n: int, rng: np.random.Generator) -> pd.DataFrame:
    age = rng.integers(17, 81, n)
    fam = rng.choice(["yes", "no", "i don't know"], n, p=[0.4, 0.55, 0.05])
    logit = -3.0 + 0.06 * age + 1.0 * (fam == "yes")
    diabetic = rng.random(n) < 1 / (1 + np.exp(-logit))
    dx = np.where(diabetic, "yes", "no").astype(object)
    dx[rng.random(n) < 0.01] = "i prefer not to say"
    prefs = ["sweet", "spicy", "sour", "salty", "oily", "dry", "light", "heavy"]
    return pd.DataFrame(
        {
            "Name": [f"Person {i} {rng.integers(1e6)}" for i in range(n)],
            "Age": age,
            "Gender": rng.choice(["female", "male"], n),
            "Prakriti": rng.choice(["vata", "pitta", "kapha", "vata-pitta", "i don't know"], n),
            "Diet": rng.choice(["vegetarian", "non-vegetarian", "vegan"], n),
            "Food Preferences": [
                ", ".join(rng.choice(prefs, rng.integers(1, 4), replace=False)) for _ in range(n)
            ],
            "Meal Timing": rng.choice(["regular", "irregular"], n),
            "Exercise": rng.choice(["yes", "no"], n),
            "Sleep Hours/Night": rng.integers(5, 10, n),
            "Sleep Quality": rng.choice(["good", "average", "poor"], n),
            "Daily Routine": rng.choice(["regular", "irregular"], n),
            "Stress Level": rng.integers(1, 6, n),
            "Diabetes Diagnosis": dx,
            "Family History of Diabetes": fam,
        }
    )


def prakriti_assessment(
    n: int, rng: np.random.Generator, n_signal: int = 6, n_items: int = 25
) -> pd.DataFrame:
    dosha = rng.choice(["Vata", "Pitta", "Kapha"], n)
    code = pd.Series(dosha).map({"Vata": 0, "Pitta": 1, "Kapha": 2}).to_numpy()
    levels = np.array(["Low", "Medium", "High"])
    cols = {}
    for j in range(n_items):
        if j < n_signal:  # answer follows the dosha 75% of the time
            ans = np.where(rng.random(n) < 0.75, code, rng.integers(0, 3, n))
        else:
            ans = rng.integers(0, 3, n)
        cols[f"Item {j + 1:02d}"] = levels[ans]
    return pd.DataFrame(cols | {"Dosha": dosha})


def condition_kb_classical(n: int, rng: np.random.Generator) -> pd.DataFrame:
    systems = list(SYSTEMS)
    rows = []
    for i in range(n):
        s = systems[i % len(systems)]
        k = rng.integers(3, 6)
        sym = list(rng.choice(SYSTEMS[s], k, replace=False))
        if rng.random() < 0.3:
            sym.append("fever")
        rows.append(
            {
                "Sr No": i + 1,
                "Ayurvedic Code": f"1/{i:03d}",
                "Ayurvedic Name": f"Roga{i:03d}ka",
                "Modern Equivalent": f"Disease {i}",
                "System / Body Part": s,
                "Dosha Predominance": DOSHA_BY_SYSTEM[s],
                "Prognosis": rng.choice(["Curable", "Difficult"]),
                "Symptoms": ", ".join(x.capitalize() for x in sym),
                "Age Group": "Any age",
                "Gender": "Both genders",
                "Treatment Principles": "Shamana",
                "Source Text": "Charaka Samhita",
            }
        )
    return pd.DataFrame(rows)


def condition_kb_modern(n: int, rng: np.random.Generator) -> pd.DataFrame:
    systems = list(SYSTEMS)
    rows = []
    for i in range(n):
        s = systems[i % len(systems)]
        rows.append(
            {
                "Disease": f"Modern disease {i}",
                "Hindi Name": "-",
                "Marathi Name": "-",
                "Symptoms": ", ".join(rng.choice(SYSTEMS[s], 3, replace=False)),
                "Doshas": DOSHA_BY_SYSTEM[s].replace("/", ", "),
                "Prognosis": "Chronic, manageable",
            }
        )
    # A planted copy-paste error: same disease, contradictory profile.
    rows.append(rows[0] | {"Symptoms": "Photophobia, halos, eye pain"})
    return pd.DataFrame(rows)


def namc(classical: pd.DataFrame) -> pd.DataFrame:
    names = [*classical["Ayurvedic Name"].iloc[::10], "vAtavyAdhiH", "jvaraH"]
    return pd.DataFrame(
        {
            "Sr No.": range(1, len(names) + 1),
            "NAMC_ID": range(1, len(names) + 1),
            "NAMC_CODE": [f"X-{i}" for i in range(len(names))],
            "NAMC_term": names,
            "NAMC_term_diacritical": names,
            "NAMC_term_DEVANAGARI": "-",
            "Short_definition": "-",
            "Long_definition": "-",
            "Ontology_branches": None,
        }
    )


SPECS = {
    "patient_intake": (
        "synthetic/intake",
        "intake.csv",
        "patient_cohort",
        "Diabetes Diagnosis",
        None,
        None,
    ),
    "prakriti_assessment": (
        "synthetic/prakriti",
        "prakriti.csv",
        "assessment",
        "Dosha",
        None,
        None,
    ),
    "condition_kb_classical": (
        "synthetic/kb-classical",
        "classical.csv",
        "knowledge_base",
        "System / Body Part",
        "Symptoms",
        "Ayurvedic Name",
    ),
    "condition_kb_modern": (
        "synthetic/kb-modern",
        "modern.csv",
        "knowledge_base",
        "Doshas",
        "Symptoms",
        "Disease",
    ),
    "namc_terminology": ("synthetic/namc", "namc.csv", "terminology", None, None, None),
}


def build(root: Path, seed: int = 7) -> Path:
    """Write all sources + a checksum-pinned registry under ``root``; return the registry path."""
    rng = np.random.default_rng(seed)
    classical = condition_kb_classical(250, rng)
    frames = {
        "patient_intake": patient_intake(700, rng),
        "prakriti_assessment": prakriti_assessment(400, rng),
        "condition_kb_classical": classical,
        "condition_kb_modern": condition_kb_modern(80, rng),
        "namc_terminology": namc(classical),
    }
    data_dir = root / "raw"
    sources = {}
    for name, (kaggle, file, role, label, text, entity) in SPECS.items():
        path = data_dir / kaggle.replace("/", "__") / file
        path.parent.mkdir(parents=True, exist_ok=True)
        frames[name].to_csv(path, index=False)
        spec = {
            "kaggle": kaggle,
            "file": file,
            "role": role,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        spec |= {
            k: v
            for k, v in {"label": label, "text_column": text, "entity_column": entity}.items()
            if v
        }
        sources[name] = spec
    registry = root / "sources.yaml"
    registry.write_text(yaml.safe_dump({"sources": sources}), encoding="utf-8")
    return registry
