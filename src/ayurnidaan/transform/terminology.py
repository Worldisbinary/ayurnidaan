"""Link classical condition names to Ministry of AYUSH NAMC codes.

Condition names arrive in loose romanisation ("Abhisyanda"); NAMC terms are in
Harvard-Kyoto / IAST ("abhiShyandaH", "abhiṣyandaḥ"). Both are reduced to a
phonetic key (diacritics, aspiration and case-ending visarga removed), then matched:

* ``exact``  - identical phonetic key (score 1.0)
* ``fuzzy``  - char n-gram cosine >= threshold on the key (candidate, needs review),
  and only if both terms carry the same dosha tags and share their first syllable.
  Without those guards, high-similarity matches flip meaning: "Asthisula" (bone pain)
  scores 0.91 against "bastiSUlaH" (bladder pain); "Kaphaja Karna Sula" against a
  Vata-only earache code.

Links are decision support for coders, never silently trusted: the score and tier are
stored next to every code.
"""

from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

_FOLD = [
    ("sh", "s"),
    ("aa", "a"),
    ("ii", "i"),
    ("uu", "u"),
    ("bh", "b"),
    ("dh", "d"),
    ("th", "t"),
    ("kh", "k"),
    ("gh", "g"),
    ("ph", "p"),
    ("ch", "c"),
    ("jh", "j"),
    ("v", "w"),
    ("ee", "i"),
    ("oo", "u"),
]


def phonetic_key(term: object) -> str:
    if not isinstance(term, str):
        return ""
    t = term.split("(")[0]  # drop qualifiers like "Arbuda (Vartmagata)"
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).casefold()
    t = re.sub(r"[^a-z]", "", t)
    t = re.sub(r"(ah|h|am|m)$", "", t)  # nominative endings / visarga
    for a, b in _FOLD:
        t = t.replace(a, b)
    return t.rstrip("a")


_DOSHA_TAGS = {"wata": "vata", "pitta": "pitta", "kapa": "kapha", "sannipat": "tridosha"}


def dosha_tags(key: str) -> frozenset[str]:
    return frozenset(v for k, v in _DOSHA_TAGS.items() if k in key)


def compatible(a: str, b: str) -> bool:
    return a[:3] == b[:3] and dosha_tags(a) == dosha_tags(b)


def link_namc(names: pd.Series, namc: pd.DataFrame, threshold: float = 0.80) -> pd.DataFrame:
    terms = namc["NAMC_term_diacritical"].fillna(namc["NAMC_term"])
    ref = pd.DataFrame({"code": namc["NAMC_CODE"], "term": terms, "key": terms.map(phonetic_key)})
    ref = ref[ref["key"].str.len() >= 3].drop_duplicates("key").reset_index(drop=True)
    exact = dict(zip(ref["key"], ref.index, strict=True))

    keys = names.map(phonetic_key)
    vec = TfidfVectorizer(analyzer="char", ngram_range=(2, 3)).fit(ref["key"])
    sim = vec.transform(keys) @ vec.transform(ref["key"]).T
    best = np.asarray(sim.argmax(axis=1)).ravel()
    best_score = np.asarray(sim.max(axis=1).todense()).ravel()

    rows = []
    for k, b, s in zip(keys, best, best_score, strict=True):
        if k in exact:
            i, tier, score = exact[k], "exact", 1.0
        elif len(k) >= 4 and s >= threshold and compatible(k, ref.at[b, "key"]):
            i, tier, score = b, "fuzzy", float(s)
        else:
            rows.append((None, None, "unlinked", float(s)))
            continue
        rows.append((ref.at[i, "code"], ref.at[i, "term"], tier, score))
    return pd.DataFrame(
        rows, columns=["namc_code", "namc_term", "namc_tier", "namc_score"], index=names.index
    )
