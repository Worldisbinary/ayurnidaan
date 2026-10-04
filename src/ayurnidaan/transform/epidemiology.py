"""Prevalence priors from Orphanet (orphadata.com, CC-BY-4.0).

The Ayurvedic knowledge bases list conditions but not how common they are, so a child
with diarrhoea and vomiting ranked Ebola above gastroenteritis. Orphanet publishes
prevalence classes for ~6,700 rare disorders.

Geography matters more than anything here: Orphanet's estimates are mostly European,
and cholera, diphtheria or polio are "<1 / 1,000,000" *in Europe* but endemic or
recently endemic in India. So a class is used only when it is given for India, South
or South-East Asia, or Worldwide (in that order of preference); a disorder with only
European / American estimates gets no adjustment.

The multiplier is square-root tempered:  w = min(1, sqrt(p / 1e-3)). Fully proportional
priors would make a rare disease unreachable even when every symptom matches, which in a
screening tool hides exactly the cases a practitioner most needs to consider.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

CLASS_MIDPOINT = {  # per person
    ">1 / 1000": 2e-3,
    "6-9 / 10 000": 7.5e-4,
    "1-5 / 10 000": 3e-4,
    "1-9 / 100 000": 5e-5,
    "1-9 / 1 000 000": 5e-6,
    "<1 / 1 000 000": 5e-7,
}
CASE_REPORTS = 2e-7  # "Cases/families" only: known from case series
GENERIC_SUFFIX = {
    "fever",
    "disease",
    "hemorrhagic",
    "haemorrhagic",
    "virus",
    "infection",
    "syndrome",
}
GEO_PREFERENCE = ("India", "South East Asia", "Asia", "Worldwide")
TYPE_PREFERENCE = (
    "Point prevalence",
    "Annual incidence",
    "Prevalence at birth",
    "Lifetime prevalence",
    "Cases/families",
)


def parse_prevalence(path: Path) -> pd.DataFrame:
    rows = []
    for d in ET.parse(path).getroot().iter("Disorder"):
        code, name = d.findtext("OrphaCode"), d.findtext("Name")
        for p in d.iter("Prevalence"):
            rows.append(
                {
                    "orphacode": code,
                    "name": name,
                    "type": p.findtext("PrevalenceType/Name"),
                    "class": p.findtext("PrevalenceClass/Name"),
                    "geography": p.findtext("PrevalenceGeographic/Name"),
                    "validation": p.findtext("PrevalenceValidationStatus/Name"),
                }
            )
    return pd.DataFrame(rows)


def parse_names(path: Path) -> pd.DataFrame:
    rows = []
    for d in ET.parse(path).getroot().iter("Disorder"):
        code = d.findtext("OrphaCode")
        if code is None:
            continue
        rows.append({"orphacode": code, "name": d.findtext("Name"), "is_synonym": False})
        rows.extend(
            {"orphacode": code, "name": s.text, "is_synonym": True}
            for s in d.iter("Synonym")
            if s.text
        )
    return pd.DataFrame(rows)


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def disorder_priors(prevalence: pd.DataFrame) -> dict[str, dict]:
    """orphacode -> {weight, class, geography, type} using the geography rule above."""
    out = {}
    for code, grp in prevalence.groupby("orphacode"):
        chosen = None
        for geo in GEO_PREFERENCE:
            g = grp[grp["geography"] == geo]
            for typ in TYPE_PREFERENCE:
                rows = g[g["type"] == typ]
                for r in rows.itertuples():
                    if typ == "Cases/families":
                        chosen = (CASE_REPORTS, "case reports only", geo, typ)
                    elif r[4] in CLASS_MIDPOINT:  # r[4] = class
                        chosen = (CLASS_MIDPOINT[r[4]], r[4], geo, typ)
                    if chosen:
                        break
                if chosen:
                    break
            if chosen:
                break
        if chosen:
            p, cls, geo, typ = chosen
            out[str(code)] = {
                "weight": round(min(1.0, math.sqrt(p / 1e-3)), 4),
                "class": cls,
                "geography": geo,
                "type": typ,
            }
    return out


def link_conditions(
    names: pd.Series, modern: pd.Series, orpha_names: pd.DataFrame, priors: dict[str, dict]
) -> list[dict | None]:
    """Exact (normalised) name / synonym match on the condition or any '/'-separated part
    of its modern equivalent. No fuzzy matching: a wrong rare-disease link would suppress
    a common condition."""
    lookup: dict[str, str] = {}
    prefixed: dict[str, set[str]] = {}
    for r in orpha_names.itertuples():
        key = norm(r.name)
        lookup.setdefault(key, str(r.orphacode))
        # "ebola hemorrhagic fever" is also reachable as "ebola", but only when everything
        # after the prefix is a generic disease word - never "psoriasis" -> a rare variant.
        words = key.split()
        for k in range(1, len(words)):
            if set(words[k:]) <= GENERIC_SUFFIX:
                prefixed.setdefault(" ".join(words[:k]), set()).add(str(r.orphacode))
    for key, codes in prefixed.items():
        if key not in lookup and len(codes) == 1:  # unambiguous only
            lookup[key] = next(iter(codes))
    display = dict(
        zip(
            orpha_names.loc[~orpha_names["is_synonym"], "orphacode"].astype(str),
            orpha_names.loc[~orpha_names["is_synonym"], "name"],
            strict=True,
        )
    )
    out = []
    for name, mod in zip(names, modern, strict=True):
        found = None
        for text in (name, mod):
            for part in re.split(r"\s*/\s*|\s*\(\s*|\)", str(text)):
                key = norm(part)
                if len(key) > 3 and key in lookup:
                    found = lookup[key]
                    break
            if found:
                break
        if found and found in priors:
            out.append({"orphacode": found, "orphanet_name": display.get(found), **priors[found]})
        else:
            out.append(None)
    return out
