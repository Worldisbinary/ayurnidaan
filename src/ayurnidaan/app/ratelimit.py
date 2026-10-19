"""Per-client rate limiting: token buckets with bounded memory, and client-IP resolution.

**Algorithm: token bucket.** Each (client, bucket) has ``capacity`` tokens that refill
continuously at ``capacity`` per minute. A request spends one token; with none left it
gets 429 and a ``Retry-After`` equal to the time until the next token. Compared with the
sliding-window log this replaces (a deque of timestamps per client):

* O(1) time and O(1) memory per client (two floats), instead of O(limit) timestamps;
* it allows short bursts up to ``capacity`` and then a smooth average rate, which suits
  search-as-you-type better than a hard window edge.

**Bounded memory.** Clients live in an LRU map capped at ``max_clients``; the least
recently seen client is dropped first. The old limiter never forgot an IP, so a scan
from many addresses grew memory without bound. A dropped client simply starts again
with a full bucket, which is the same as being idle for a minute.

**Client IP behind proxies.** nginx and Render's edge each append the address they saw
to ``X-Forwarded-For``. The left part of that header is whatever the client sent, so
trusting it would let anyone pick a fresh "IP" per request and never be limited. We count
``trusted_proxy_hops`` entries from the *right* instead: with one proxy in front
(nginx, or Render), the last entry is the address that proxy actually saw.

**Scope.** State is per worker process. With W workers a client can get up to W x the
limit in the worst case; nginx's ``limit_req`` in front is the shared, exact limit, and
this is the defence in depth for platforms without nginx (Render). A multi-instance
deployment would move this to Redis (see docs/SYSTEM_DESIGN.md).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: float  # seconds until one token is available (0 when allowed)


class TokenBucketLimiter:
    def __init__(
        self,
        per_minute: dict[str, int],
        max_clients: int = 50_000,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.capacity = dict(per_minute)
        self.rate = {k: v / 60.0 for k, v in per_minute.items()}  # tokens per second
        self.max_clients = max_clients
        self._clock = clock
        self._buckets: OrderedDict[tuple[str, str], list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, client: str, bucket: str) -> Decision:
        cap, rate, now = self.capacity[bucket], self.rate[bucket], self._clock()
        key = (client, bucket)
        with self._lock:
            state = self._buckets.get(key)
            if state is None:
                state = [float(cap), now]
                self._buckets[key] = state
                if len(self._buckets) > self.max_clients:
                    self._buckets.popitem(last=False)
            else:
                self._buckets.move_to_end(key)
                tokens, last = state
                state[0] = min(cap, tokens + (now - last) * rate)
                state[1] = now
            if state[0] >= 1:
                state[0] -= 1
                return Decision(True, cap, int(state[0]), 0.0)
            return Decision(False, cap, 0, (1 - state[0]) / rate)

    def __len__(self) -> int:
        return len(self._buckets)


def client_ip(peer: str | None, forwarded_for: str | None, trusted_hops: int) -> str:
    """The client address as seen by the outermost proxy we trust.

    ``trusted_hops`` = number of proxies in front of the app that append to
    X-Forwarded-For (0 = the app is exposed directly; use the socket peer).
    """
    if trusted_hops > 0 and forwarded_for:
        hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
        if len(hops) >= trusted_hops:
            return hops[-trusted_hops]
    return peer or "unknown"
