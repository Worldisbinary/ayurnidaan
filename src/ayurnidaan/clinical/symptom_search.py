"""Map what a patient types ("my joints ache", "loose motions") to canonical symptoms.

Lookup order:

1. exact canonical term or alias (score 1.0);
2. prefix completions from a trie (``trie.PrefixTrie``): phrases that start with the
   query (0.9) or have a word that starts with it (0.8). This is autocomplete; when it
   finds anything, the fuzzy step is skipped;
3. only when nothing matches as a prefix (usually a typo, "diarhea"): character n-gram
   (TF-IDF) similarity over all terms and aliases. Below the similarity floor nothing is
   matched rather than guessing.

Complexity per query: step 2 is O(p + k) (p = query length); step 3 is O(K) over the K
indexed phrases plus a sparse vector product, and runs only for queries with no prefix
hit. ``scripts/bench_hotpaths.py`` measures both.
"""

from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer

from ..transform.symptoms import normalize_phrase
from .trie import FULL_PREFIX, PrefixTrie

EXACT, FULL, WORD = 1.0, 0.9, 0.8


class SymptomIndex:
    def __init__(self, symptoms: list[dict], floor: float = 0.55):
        self.floor = floor
        self.lookup: dict[str, str] = {}
        for s in symptoms:
            self.lookup[s["term"]] = s["term"]
            for a in s.get("aliases", []):
                self.lookup.setdefault(a, s["term"])
        self.keys = list(self.lookup)
        self.freq = {s["term"]: s["doc_freq"] for s in symptoms}
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
        self.matrix = self.vec.fit_transform(self.keys)
        self.trie = PrefixTrie(k=20)
        for key, term in self.lookup.items():
            self.trie.insert(key, term, self.freq.get(term, 0))
        self.trie.build()

    def _prefix_hits(self, q: str, limit: int, word_prefix: bool) -> dict[str, float]:
        hits: dict[str, float] = {}
        if q in self.lookup:
            hits[self.lookup[q]] = EXACT
        for term, cls in self.trie.complete(q, limit=limit):
            if cls == FULL_PREFIX:
                hits.setdefault(term, FULL)
            elif word_prefix:
                hits.setdefault(term, WORD)
        return hits

    def search(self, query: str, limit: int = 8, always_fuzzy: bool = False) -> list[dict]:
        """Autocomplete by default. ``always_fuzzy`` is for mapping free text to one best
        symptom: it also scores fuzzy candidates and ignores mid-phrase word matches."""
        q = query.casefold().strip()
        if not q:
            return []
        norm = normalize_phrase(q) or q
        word = not always_fuzzy
        best = self._prefix_hits(q, limit, word)
        if norm != q:
            for term, score in self._prefix_hits(norm, limit, word).items():
                best[term] = max(score, best.get(term, 0.0))
        # Prefix first, fuzzy as the fallback: when the text is the start of a real symptom
        # the completions are the answer, and n-gram look-alikes would only add noise. The
        # fuzzy pass is for typos (no prefix hit) and for callers that want one best match.
        if always_fuzzy or not best:
            sims = (self.vec.transform([norm]) @ self.matrix.T).toarray().ravel()
            for i in sims.nonzero()[0]:
                term = self.lookup[self.keys[i]]
                if sims[i] > best.get(term, 0.0):
                    best[term] = float(sims[i])
        ranked = sorted(best.items(), key=lambda kv: (-kv[1], -self.freq.get(kv[0], 0), kv[0]))
        return [{"term": t, "score": round(s, 3)} for t, s in ranked[:limit] if s >= 0.3]

    def best(self, text: str) -> str | None:
        norm = normalize_phrase(text.casefold().strip()) or text.casefold().strip()
        if norm in self.lookup:
            return self.lookup[norm]
        # Free text from the intake: weigh every candidate, including fuzzy ones.
        hits = self.search(text, limit=1, always_fuzzy=True)
        return hits[0]["term"] if hits and hits[0]["score"] >= self.floor else None
