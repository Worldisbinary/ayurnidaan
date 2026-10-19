"""Top-k selection for ranking the differential.

The ranking needs the best ~10 of ~1,400 condition scores, but with a twist: the same
disease can appear in both knowledge bases, and duplicates are skipped, so we do not know
in advance how many candidates we will consume. A full ``argsort`` is O(n log n) for
every assessment. ``descending`` instead:

1. selects the best ``m`` (a few times k) with ``np.argpartition`` (introselect,
   O(n) on average), sorts only those (O(m log m)), and yields them in order;
2. only if the caller consumes all ``m`` (many duplicates) does it sort the rest.

This is the vectorised form of keeping a size-k heap: in Python, ``heapq.nlargest``
is O(n log k) but runs per element in the interpreter, which is slower than one numpy
call at this n. Ties are broken by index, so the order is deterministic.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np


def descending(scores: np.ndarray, expect: int, slack: int = 4) -> Iterator[int]:
    n = len(scores)
    m = min(n, max(expect * slack, expect + 8))
    if m >= n:
        yield from _sorted_desc(scores, np.arange(n))
        return
    head = np.argpartition(-scores, m - 1)[:m]
    yield from _sorted_desc(scores, head)
    rest = np.setdiff1d(np.arange(n), head, assume_unique=True)
    yield from _sorted_desc(scores, rest)


def _sorted_desc(scores: np.ndarray, idx: np.ndarray) -> Iterator[int]:
    # lexsort: last key is primary -> score descending, then index ascending
    order = np.lexsort((idx, -scores[idx]))
    for i in idx[order]:
        yield int(i)
