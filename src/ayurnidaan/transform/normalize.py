"""Conformed dimensions and per-source cleaning.

The three source domains share no patient keys, so integration happens through
*conformed dimensions* - every source's dosha and body-system vocabulary is mapped
onto one canonical code set, which is what lets the dashboard put patient prevalence,
assessment results and condition burden side by side.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

DOSHAS = ("vata", "pitta", "kapha")
# Canonical order for dual doshas so "Pitta-Vata" and "vata+pitta" collapse.
_ORDER = {d: i for i, d in enumerate(DOSHAS)}
_NON_DOSHA = {"rakta", "meda", "agantuja", "ama"}


def canonical_dosha(value: object) -> str | None:
    """Map any dosha spelling to vata | pitta | kapha | vata-pitta | ... | tridosha.

    Non-dosha tags (rakta, agantuja = exogenous) are dropped; if nothing remains the
    value is unknown. "i don't know" responses become None (handled as missing).
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).casefold()
    if "tridosha" in text or "sannipata" in text:
        return "tridosha"
    found = sorted({d for d in DOSHAS if d in text}, key=_ORDER.get)
    if not found:
        return None
    if len(found) == 3:
        return "tridosha"
    return "-".join(found)


def dosha_components(code: object) -> list[str]:
    if not isinstance(code, str):  # None / NaN / pd.NA
        return []
    return list(DOSHAS) if code == "tridosha" else code.split("-")


_SYSTEM_ALIASES = {
    "gastrointestinal": "digestive",
    "abdomen": "digestive",
    "ano-rectal": "digestive",
    "digestive": "digestive",
    "liver": "digestive",
    "mouth": "oral-dental",
    "teeth": "oral-dental",
    "nose": "ent",
    "ear": "ent",
    "throat": "ent",
    "head": "nervous",
    "nervous": "nervous",
    "mental": "mental",
    "psychiatric": "mental",
    "eye": "eye",
    "skin": "skin",
    "urinary": "urinary",
    "renal": "urinary",
    "musculoskeletal": "musculoskeletal",
    "joints": "musculoskeletal",
    "gynaecology": "reproductive",
    "obstetrics": "reproductive",
    "reproductive": "reproductive",
    "male": "reproductive",
    "respiratory": "respiratory",
    "cardiovascular": "cardiovascular",
    "heart": "cardiovascular",
    "blood": "blood",
    "metabolic": "metabolic",
    "endocrine": "metabolic",
    "paediatric": "paediatric",
    "systemic": "systemic",
    "toxicology": "systemic",
    "infectious": "systemic",
}


def canonical_body_system(value: object) -> str:
    """Primary body system = first recognised token of e.g. 'Nervous/Musculoskeletal'."""
    if not isinstance(value, str):
        return "unspecified"
    for token in re.split(r"[/,&]| and ", value.casefold()):
        token = token.strip()
        for key, system in _SYSTEM_ALIASES.items():
            if key in token:
                return system
    return "other"


UNKNOWN_TOKENS = {"i don't know", "i dont know", "i prefer not to say", "prefer not to say", ""}


def clean_patient_intake(df: pd.DataFrame) -> pd.DataFrame:
    """Typed, analysis-ready intake records (post-PII-scrub).

    Explicit "don't know" answers are kept as their own level *and* flagged, because
    in this cohort non-response is informative (see the variables report).
    """
    out = pd.DataFrame({"record_id": df["record_id"], "patient_key": df["patient_key"]})
    out["age"] = pd.to_numeric(df["Age"], errors="coerce").astype("Int64")
    out["gender"] = df["Gender"].str.casefold().str.strip()
    out["prakriti_raw"] = df["Prakriti"].str.casefold().str.strip()
    out["dosha"] = out["prakriti_raw"].map(canonical_dosha)
    out["diet"] = df["Diet"].str.casefold().str.strip()
    out["meal_timing"] = df["Meal Timing"].str.casefold().str.strip()
    out["exercise"] = df["Exercise"].str.casefold().eq("yes")
    out["sleep_hours"] = pd.to_numeric(df["Sleep Hours/Night"], errors="coerce")
    out["sleep_quality"] = df["Sleep Quality"].str.casefold().str.strip()
    out["daily_routine"] = df["Daily Routine"].str.casefold().str.strip()
    out["stress_level"] = pd.to_numeric(df["Stress Level"], errors="coerce").astype("Int64")
    fam = df["Family History of Diabetes"].str.casefold().str.strip()
    out["family_history"] = fam.where(~fam.isin(UNKNOWN_TOKENS), "unknown")
    dx = df["Diabetes Diagnosis"].str.casefold().str.strip()
    out["diabetes"] = dx.map({"yes": 1, "no": 0}).astype("Int64")  # NA = declined to answer

    prefs = df["Food Preferences"].fillna("").str.casefold().str.split(r",\s*")
    tokens = sorted({t.strip() for row in prefs for t in row if t.strip()})
    for tok in tokens:
        out[f"pref_{re.sub(r'[^a-z]+', '_', tok)}"] = prefs.map(lambda r, t=tok: t in r)
    out["n_food_prefs"] = prefs.map(lambda r: sum(bool(t.strip()) for t in r))
    return out


def snake(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")


def clean_prakriti_assessment(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [snake(c) for c in out.columns]
    out["dosha"] = out["dosha"].map(canonical_dosha)
    out.insert(0, "assessment_id", np.arange(1, len(out) + 1))
    return out
