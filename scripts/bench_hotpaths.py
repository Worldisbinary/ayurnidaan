"""Micro-benchmarks for the API's CPU hot paths, on the real knowledge pack.

    python scripts/bench_hotpaths.py            # prints a table; numbers vary by machine

Measures what docs/SYSTEM_DESIGN.md quotes:
  * symptom autocomplete: every prefix of every symptom name (what typing produces)
  * the same with the response cache warm (repeat keystrokes / many users)
  * the differential ranking step for a typical 3-symptom intake
Run it before and after a change to the engine or the search; never hand-edit numbers.
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ayurnidaan.clinical.differential import DifferentialModel
from ayurnidaan.clinical.knowledge import KnowledgePack
from ayurnidaan.clinical.symptom_search import SymptomIndex


def timed(fn, items) -> list[float]:
    out = []
    for it in items:
        t = time.perf_counter()
        fn(it)
        out.append((time.perf_counter() - t) * 1e6)
    return out


def summary(name: str, us: list[float]) -> str:
    us = sorted(us)
    p = lambda q: us[min(len(us) - 1, int(q * len(us)))]  # noqa: E731
    return f"{name:38} n={len(us):5}  p50 {p(0.5):8.1f} us  p95 {p(0.95):8.1f} us  mean {statistics.mean(us):8.1f} us"


def main() -> None:
    pack = KnowledgePack.load(Path(__file__).resolve().parents[1] / "knowledge_pack")
    index = SymptomIndex(pack.symptoms)
    prefixes = sorted({s["term"][:i] for s in pack.symptoms for i in range(1, len(s["term"]) + 1)})
    print(summary("symptom search (cold, all prefixes)", timed(index.search, prefixes)))

    from ayurnidaan.app.cache import TTLCache

    cache = TTLCache("bench", maxsize=4096, ttl_seconds=None)
    warm = lambda q: cache.get_or_compute(q, lambda: index.search(q))  # noqa: E731
    for q in prefixes:
        warm(q)
    print(summary("symptom search (cache warm)", timed(warm, prefixes)))

    model = DifferentialModel(pack)
    answers = {"cough": True, "fever": True, "headache": True}
    parts = model.log_scores(answers, age=35, sex="female")
    post = model.posterior(parts)
    print(
        summary(
            "differential rank top-10",
            timed(lambda _: model.rank(post, parts, answers), range(2000)),
        )
    )
    print(
        f"conditions={len(model.conditions)}  symptom keys={len(index.keys)}  prefixes={len(prefixes)}"
    )


if __name__ == "__main__":
    main()
