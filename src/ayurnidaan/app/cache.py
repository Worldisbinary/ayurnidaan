"""In-process LRU cache with per-entry time-to-live.

Used for read-heavy data that is expensive to compute or fetch and safe to serve
slightly stale:

* place search (``/geo/search``): each miss is an outbound HTTPS call to Open-Meteo
  (100-400 ms, and their fair-use limit); place names do not change, so a day is fine.
* symptom autocomplete (``/symptoms/search``): pure CPU, keyed by knowledge-pack
  version, so a new pack can never serve old results.

Data structure: an ``OrderedDict`` is a hash map threaded through a doubly linked list,
the textbook LRU layout. ``get`` moves the key to the most-recent end and ``put`` evicts
from the least-recent end, both O(1). Expired entries are dropped lazily when they are
read, so there is no background thread. A lock makes it safe under the threadpool that
FastAPI runs sync endpoints in.

Scope: one cache per worker process. With N workers the hit rate is a bit lower and
memory is N x ``maxsize`` entries (still tiny here). A shared cache (Redis) would be the
next step only if the miss cost or the worker count grows; see docs/SYSTEM_DESIGN.md.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any

from .observability import CACHE_REQUESTS

_MISSING = object()


class TTLCache:
    def __init__(
        self,
        name: str,
        maxsize: int = 1024,
        ttl_seconds: float | None = 3600,
        clock: Callable[[], float] = time.monotonic,
    ):
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self.name = name
        self.maxsize = maxsize
        self.ttl = ttl_seconds
        self._clock = clock
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = self.evictions = 0

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            item = self._data.get(key, _MISSING)
            if item is _MISSING:
                self.misses += 1
                return default
            expires, value = item
            if expires < self._clock():
                del self._data[key]
                self.misses += 1
                return default
            self._data.move_to_end(key)
            self.hits += 1
            return value

    def put(self, key: Hashable, value: Any) -> None:
        expires = self._clock() + self.ttl if self.ttl is not None else float("inf")
        with self._lock:
            self._data[key] = (expires, value)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)
                self.evictions += 1

    def get_or_compute(self, key: Hashable, compute: Callable[[], Any]) -> Any:
        """Return the cached value, or compute, store and return it.

        ``compute`` runs outside the lock, so two concurrent misses on one key may both
        compute it (harmless here: both results are equal). Exceptions are not cached.
        """
        value = self.get(key, _MISSING)
        if value is _MISSING:
            CACHE_REQUESTS.labels(self.name, "miss").inc()
            value = compute()
            self.put(key, value)
        else:
            CACHE_REQUESTS.labels(self.name, "hit").inc()
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "name": self.name,
            "size": len(self._data),
            "maxsize": self.maxsize,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_ratio": round(self.hits / total, 3) if total else None,
        }
