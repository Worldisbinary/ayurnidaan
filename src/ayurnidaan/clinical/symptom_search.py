"""Map what a patient types ("my joints ache", "loose motions") to canonical symptoms.

Lookup order: exact canonical term or alias -> the same after the vocabulary's own
normalisation (spelling, synonyms, qualifiers) -> character n-gram similarity over
terms and aliases. Below the similarity floor nothing is matched rather than guessing.
"""

from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer

from ..transform.symptoms import normalize_phrase


class SymptomIndex:
    def __init__(self, symptoms: list[dict], floor: float = 0.55):
        self.floor = floor
        self.lookup: dict[str, str] = {}
        for s in symptoms:
            self.lookup[s["term"]] = s["term"]
            for a in s.get("aliases", []):
                self.lookup.setdefault(a, s["term"])
        self.keys = list(self.lookup)
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
        self.matrix = self.vec.fit_transform(self.keys)
        self.freq = {s["term"]: s["doc_freq"] for s in symptoms}

    def search(self, query: str, limit: int = 8) -> list[dict]:
        q = query.casefold().strip()
        if not q:
            return []
        norm = normalize_phrase(q) or q
        sims = (self.vec.transform([norm]) @ self.matrix.T).toarray().ravel()
        best: dict[str, float] = {}
        for key, score in zip(self.keys, sims, strict=True):
            term = self.lookup[key]
            if key.startswith(norm):
                score = max(score, 0.9)
            if score > best.get(term, 0):
                best[term] = float(score)
        ranked = sorted(best.items(), key=lambda kv: (-kv[1], -self.freq.get(kv[0], 0)))
        return [{"term": t, "score": round(s, 3)} for t, s in ranked[:limit] if s >= 0.3]

    def best(self, text: str) -> str | None:
        norm = normalize_phrase(text.casefold().strip()) or text.casefold().strip()
        if norm in self.lookup:
            return self.lookup[norm]
        hits = self.search(text, limit=1)
        return hits[0]["term"] if hits and hits[0]["score"] >= self.floor else None
