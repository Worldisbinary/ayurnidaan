"""Symptom canonicalisation: free-text symptom lists -> controlled vocabulary.

Pipeline per mention:  split -> strip qualifiers/parentheticals -> spelling
normalisation (British -> US medical spelling) -> curated synonym map. A fitted
vocabulary then (1) merges remaining near-duplicates ("joint pains" / "joint pain")
using character n-gram cosine similarity, mapping each variant onto its most frequent
form, and (2) backs off rare phrases to the longest frequent term they contain
("redness of eye" -> "redness", "sticky discharge" -> "discharge").

Every raw -> canonical decision is kept in ``aliases`` so the mapping is auditable.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

_QUALIFIERS = (
    "severe",
    "mild",
    "moderate",
    "chronic",
    "acute",
    "recurrent",
    "persistent",
    "intermittent",
    "frequent",
    "excessive",
    "increased",
    "marked",
    "progressive",
    "sudden",
    "occasional",
    "slight",
    "extreme",
    "intense",
    "constant",
    "general",
    "generalized",
    "generalised",
    "localized",
    "localised",
    "bilateral",
    "unilateral",
    "significant",
    "gradual",
    "episodic",
    "prolonged",
    "repeated",
    "profuse",
    "very",
    "some",
    "possible",
)
_QUALIFIER_RE = re.compile(rf"^(?:(?:{'|'.join(_QUALIFIERS)})\s+)+")

# Fragments produced by splitting descriptive phrases ("Hard, non-tender swelling").
_DESCRIPTOR_ONLY = {
    "hard",
    "soft",
    "warm",
    "cold",
    "non-tender",
    "tender",
    "painless",
    "slow growing",
    "smooth",
    "firm",
    "mobile",
    "fixed",
    "small",
    "large",
    "thick",
    "thin",
    "white",
    "red",
    "yellow",
    "black",
    "dark",
    "pale",
    "sticky",
    "foul",
    "round",
    "irregular",
    "dry",
    "moist",
    "rough",
    "shiny",
    "slow",
    "fast",
    "etc",
    "others",
    "other symptoms",
    "variable",
    "associated",
    "especially",
    "symptoms",
    "signs",
    "condition",
    "cases",
    "may",
    "later",
    "chronic",
    "course",
    "deep",
    "dull",
    "eyes",
    "feet",
    "hot",
    "movement",
    "onset",
    "recurrent",
    "severe",
    "sweet",
    "worse",
    "worsens",
    "refractory",
    "pulsatile",
    "mixed features",
    "pitting",
    "blood",
    "heat",
    "infections",
    "frequency",
    "systemic features",
    "systemic disease",
    "neurological symptoms",
    "skin changes",
    "watering",
    "urination",
    "wasting",
}

_SPELLING = [
    (r"oedema", "edema"),
    (r"oea\b", "ea"),
    (r"diarrhoea", "diarrhea"),
    (r"haem", "hem"),
    (r"anaem", "anem"),
    (r"aemia", "emia"),
    (r"oesoph", "esoph"),
    (r"colour", "color"),
    (r"tumour", "tumor"),
    (r"behaviour", "behavior"),
    (r"paediatric", "pediatric"),
]

SYNONYMS = {
    "breathlessness": "shortness of breath",
    "dyspnea": "shortness of breath",
    "difficulty breathing": "shortness of breath",
    "difficulty in breathing": "shortness of breath",
    "breathing difficulty": "shortness of breath",
    "labored breathing": "shortness of breath",
    "high blood pressure": "hypertension",
    "elevated blood pressure": "hypertension",
    "tiredness": "fatigue",
    "exhaustion": "fatigue",
    "lethargy": "fatigue",
    "debility": "weakness",
    "body weakness": "weakness",
    "emesis": "vomiting",
    "anorexia": "loss of appetite",
    "poor appetite": "loss of appetite",
    "reduced appetite": "loss of appetite",
    "decreased appetite": "loss of appetite",
    "appetite loss": "loss of appetite",
    "pruritus": "itching",
    "itchiness": "itching",
    "itchy skin": "itching",
    "pyrexia": "fever",
    "high fever": "fever",
    "low-grade fever": "fever",
    "low grade fever": "fever",
    "sleeplessness": "insomnia",
    "difficulty sleeping": "insomnia",
    "sleep disturbance": "insomnia",
    "sleep disturbances": "insomnia",
    "painful": "pain",
    "aches": "pain",
    "ache": "pain",
    "pains": "pain",
    "dryness": "dryness",
    "loose stools": "diarrhea",
    "loose motions": "diarrhea",
    "watery stools": "diarrhea",
    "frequent urination": "polyuria",
    "excessive urination": "polyuria",
    "excessive thirst": "thirst",
    "polydipsia": "thirst",
    "swollen": "swelling",
    "inflammation": "swelling",
    "puffiness": "swelling",
    "giddiness": "dizziness",
    "vertigo": "dizziness",
    "lightheadedness": "dizziness",
    "body ache": "body pain",
    "body aches": "body pain",
    "muscle aches": "muscle pain",
    "myalgia": "muscle pain",
    "arthralgia": "joint pain",
    "joint pains": "joint pain",
    "stomach pain": "abdominal pain",
    "abdominal discomfort": "abdominal pain",
    "stomach ache": "abdominal pain",
    "tummy pain": "abdominal pain",
    "skin rash": "rash",
    "rashes": "rash",
    "skin rashes": "rash",
    "weight gain": "weight gain",
    "obesity": "weight gain",
    "burning": "burning sensation",
    "heartburn": "acidity",
    "hyperacidity": "acidity",
    "acid reflux": "acidity",
    "sour belching": "acidity",
    "anxiety": "anxiety",
    "palpitation": "palpitations",
    "heavy": "heaviness",
    "coughing": "cough",
    "inflamed": "swelling",
    "thickened": "thickening",
    "headaches": "headache",
    "heavy feeling": "heaviness",
    "feeling of heaviness": "heaviness",
    "heaviness of body": "heaviness",
    "watering eyes": "lacrimation",
    "watery eyes": "lacrimation",
    "excessive lacrimation": "lacrimation",
    "jaundice": "jaundice",
    "yellowing of skin": "jaundice",
}


def split_symptoms(text: object) -> list[str]:
    if not isinstance(text, str):
        return []
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text)
    parts = re.split(r"[,;/•\n]|\band\b|\bwith\b", text)
    return [p for p in (normalize_phrase(x) for x in parts) if p]


def normalize_phrase(phrase: str) -> str | None:
    p = phrase.casefold().strip()
    p = re.sub(r"[^a-z0-9\s\-']", " ", p)
    p = re.sub(r"\s+", " ", p).strip(" -'")
    p = _QUALIFIER_RE.sub("", p)
    for pat, rep in _SPELLING:
        p = re.sub(pat, rep, p)
    p = SYNONYMS.get(p, p)
    if len(p) < 3 or p in _DESCRIPTOR_ONLY or p.isdigit():
        return None
    return p


@dataclass
class SymptomVocabulary:
    """Fitted controlled vocabulary with near-duplicate merging."""

    similarity: float = 0.88
    min_df: int = 3
    canonical: dict[str, str] = field(default_factory=dict)  # variant -> canonical
    backoff: dict[str, str] = field(default_factory=dict)  # subset of canonical: head-term backoffs
    doc_freq: Counter = field(default_factory=Counter)

    def fit(self, docs: list[list[str]]) -> SymptomVocabulary:
        raw_df = Counter(t for d in docs for t in set(d))
        terms = sorted(raw_df, key=lambda t: (-raw_df[t], t))
        self.canonical = {t: t for t in terms}
        # Plural folding first: deterministic and cheaper than similarity search.
        for t in terms:
            for stem in (
                (t[:-2], t[:-1]) if t.endswith("es") else (t[:-1],) if t.endswith("s") else ()
            ):
                if stem in raw_df and raw_df[stem] >= raw_df[t]:
                    self.canonical[t] = stem
                    break
        if len(terms) > 1:
            vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4), sublinear_tf=True)
            m = vec.fit_transform(terms)
            sim = (m @ m.T).tocsr()
            # Greedy: walk terms by descending frequency; each unassigned variant similar to
            # an already-canonical, more frequent term is merged into it.
            for j, term in enumerate(terms):
                if self.canonical[term] != term:
                    continue
                row = sim.getrow(j)
                for i, s in zip(row.indices, row.data, strict=True):
                    if (
                        i < j
                        and s >= self.similarity
                        and self.canonical[terms[i]] == terms[i]
                        and _safe_merge(term, terms[i])
                    ):
                        self.canonical[term] = terms[i]
                        break
        self.doc_freq = Counter(c for d in docs for c in {self.canonical[t] for t in d})

        frequent = {t for t, n in self.doc_freq.items() if n >= self.min_df}
        self.backoff = {}
        for term, canon in self.canonical.items():
            if canon not in frequent and (head := _longest_contained(canon, frequent)):
                self.canonical[term] = head
                self.backoff[term] = head
        self.doc_freq = Counter(c for d in docs for c in {self.canonical[t] for t in d})
        return self

    def transform(self, doc: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for t in doc:
            c = self.canonical.get(t, t)
            if self.doc_freq.get(c, 0) >= self.min_df:
                seen[c] = None
        return list(seen)

    @property
    def terms(self) -> list[str]:
        return sorted(c for c, n in self.doc_freq.items() if n >= self.min_df)

    def aliases(self) -> list[tuple[str, str]]:
        return sorted((v, c) for v, c in self.canonical.items() if v != c)

    def coverage(self, docs: list[list[str]]) -> float:
        """Share of symptom mentions that survive canonicalisation + min_df filtering."""
        total = sum(len(d) for d in docs)
        kept = sum(len(self.transform(d)) for d in docs)
        return kept / total if total else 0.0


def _longest_contained(phrase: str, vocab: set[str]) -> str | None:
    words = phrase.split()
    for n in range(len(words) - 1, 0, -1):
        for i in range(len(words) - n + 1):
            cand = " ".join(words[i : i + n])
            if cand in vocab:
                return cand
    return None


_NEGATING_PREFIXES = ("hyper", "hypo", "non", "an", "dys", "poly", "oligo")


def _safe_merge(variant: str, target: str) -> bool:
    """Block merges that flip meaning (hypertension/hypotension, polyuria/oliguria)."""
    if set(re.findall(r"\d+", variant)) != set(re.findall(r"\d+", target)):
        return False
    for pre in _NEGATING_PREFIXES:
        if variant.startswith(pre) != target.startswith(pre):
            return False
    vw, tw = variant.split(), target.split()
    # Same number of words, or a plural/singular of the same phrase.
    return len(vw) == len(tw) and all(
        a == b or a.rstrip("s") == b.rstrip("s") or _edit_close(a, b)
        for a, b in zip(vw, tw, strict=True)
    )


def _edit_close(a: str, b: str) -> bool:
    """Levenshtein distance <= 1 for words of length >= 6 (spelling variants)."""
    if min(len(a), len(b)) < 6 or abs(len(a) - len(b)) > 1:
        return False
    prev = np.arange(len(b) + 1)
    for i, ca in enumerate(a, 1):
        cur = np.empty_like(prev)
        cur[0] = i
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return int(prev[-1]) <= 1
