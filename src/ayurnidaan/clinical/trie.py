"""Prefix trie with precomputed top-k completions, for symptom autocomplete.

The intake screen searches symptoms as the patient types ("lo" -> "loose motions",
"loss of appetite", ...). Each keystroke used to score every one of the ~2,800 symptom
names and aliases. A trie answers "which phrases start with this prefix" by walking one
node per typed character, and because every node stores its best ``k`` completions
(computed once at build time), the answer is ready-made at the node:

    build:    O(L * k log k) for L total characters indexed (once, at start-up)
    complete: O(p + m) for a prefix of length p and m <= k returned completions,
              independent of the vocabulary size

Phrases are indexed at every word start, not only at the beginning, so "pain" also
completes "abdominal pain" and "joint pain". A match at the start of the whole phrase
ranks above a match inside it; within each group, more common symptoms (higher document
frequency in the knowledge base) rank first.

Top-k per node uses a bounded merge: a node's list is the k best of its own entries and
its children's lists, taken with ``heapq.nsmallest`` (a size-k heap) in a post-order
walk, so no node ever sorts more than its children's k-lists.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

FULL_PREFIX, WORD_PREFIX = 0, 1  # match classes: lower ranks first


@dataclass
class _Node:
    children: dict[str, _Node] = field(default_factory=dict)
    entries: list[tuple] = field(default_factory=list)  # phrases ending here
    top: list[tuple] = field(default_factory=list)  # best k completions in this subtree


class PrefixTrie:
    def __init__(self, k: int = 20):
        self.k = k
        self.root = _Node()
        self.size = 0  # number of indexed (phrase, start) pairs
        self._built = False

    def insert(self, phrase: str, value: str, weight: float) -> None:
        """Index ``phrase`` (lower-cased) at every word start; completions return ``value``."""
        words = phrase.casefold().split()
        for i in range(len(words)):
            suffix = " ".join(words[i:])
            node = self.root
            for ch in suffix:
                node = node.children.setdefault(ch, _Node())
            # Sort key: match class, then most frequent first, then alphabetical.
            node.entries.append((FULL_PREFIX if i == 0 else WORD_PREFIX, -weight, value))
            self.size += 1
        self._built = False

    def build(self) -> PrefixTrie:
        """Precompute each node's top-k completions (iterative post-order, no recursion)."""
        stack: list[tuple[_Node, bool]] = [(self.root, False)]
        while stack:
            node, children_done = stack.pop()
            if not children_done:
                stack.append((node, True))
                stack.extend((child, False) for child in node.children.values())
                continue
            candidates = list(node.entries)
            for child in node.children.values():
                candidates.extend(child.top)
            node.top = self._best(candidates)
        self._built = True
        return self

    def _best(self, candidates: list[tuple]) -> list[tuple]:
        # One value can arrive by several phrases (a term and its aliases): keep its best.
        best: dict[str, tuple] = {}
        for c in candidates:
            if c[2] not in best or c < best[c[2]]:
                best[c[2]] = c
        return heapq.nsmallest(self.k, best.values())

    def complete(self, prefix: str, limit: int = 8) -> list[tuple[str, int]]:
        """Up to ``limit`` (value, match_class) pairs whose indexed phrase starts with prefix."""
        if not self._built:
            raise RuntimeError("call build() after inserting")
        node = self.root
        for ch in prefix.casefold():
            node = node.children.get(ch)
            if node is None:
                return []
        return [(value, cls) for cls, _, value in node.top[:limit]]
