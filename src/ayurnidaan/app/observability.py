"""Observability: request IDs, Prometheus metrics and the /metrics exposition.

Three signals, following the SRE "golden signals" (latency, traffic, errors, saturation):

* **Logs**: one structured JSON line per request (see ``logging_utils``). Every line
  written while a request is being handled carries its ``request_id``, taken from the
  ``X-Request-ID`` header (nginx sets it) or generated here, and echoed back in the
  response so a user-reported error can be found in the logs.
* **Metrics**: Prometheus counters and histograms below, labelled by route *template*
  (``/api/v1/encounters/{encounter_id}``), never by raw path, so label cardinality stays
  bounded no matter how many encounters exist.
* **Health**: ``/healthz`` (liveness) and ``/readyz`` (readiness), in ``main.py``.

Multi-worker: uvicorn runs several worker processes, and each has its own counters. If
``PROMETHEUS_MULTIPROC_DIR`` is set (the Docker entrypoint sets it), every worker writes
its samples to files there and ``/metrics`` aggregates them, so one scrape sees the
whole container instead of whichever worker answered.
"""

from __future__ import annotations

import os
import re
import uuid

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)

from ..logging_utils import request_id_var

__all__ = ["request_id_var"]

# Accept a caller's request ID only if it is short and plain; anything else could inject
# fake fields or line breaks into the logs.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def resolve_request_id(header_value: str | None) -> str:
    if header_value and _SAFE_ID.match(header_value):
        return header_value
    return uuid.uuid4().hex[:16]


# Buckets cover a fast cached lookup (~1 ms) up to a cold-start request on the free tier.
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

HTTP_REQUESTS = Counter(
    "ayur_http_requests_total", "HTTP requests by route and status", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "ayur_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=LATENCY_BUCKETS,
)
HTTP_EXCEPTIONS = Counter(
    "ayur_http_exceptions_total", "Unhandled exceptions by route", ["route", "exception"]
)
HTTP_IN_PROGRESS = Gauge(
    "ayur_http_requests_in_progress", "Requests being served", multiprocess_mode="livesum"
)
RATE_LIMITED = Counter("ayur_rate_limited_total", "Requests refused with 429", ["bucket"])
CACHE_REQUESTS = Counter(
    "ayur_cache_requests_total", "In-process cache lookups", ["cache", "result"]
)
IDEMPOTENT_REPLAYS = Counter(
    "ayur_idempotent_replays_total", "Writes answered from a stored response", ["route"]
)
ASSESSMENT_LATENCY = Histogram(
    "ayur_engine_assessment_seconds",
    "Clinical engine: one full assessment (triage, dosha, differential, next questions)",
    buckets=LATENCY_BUCKETS,
)
DB_POOL_CHECKED_OUT = Gauge(
    "ayur_db_pool_checked_out",
    "Database connections currently in use",
    multiprocess_mode="livesum",
)
BUILD_INFO = Gauge(
    "ayur_build_info",
    "Running version, commit and knowledge pack (value is always 1)",
    ["version", "commit", "knowledge_pack"],
    multiprocess_mode="max",
)


def metrics_payload() -> tuple[bytes, str]:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry), CONTENT_TYPE_LATEST
    from prometheus_client import REGISTRY

    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def mark_worker_dead() -> None:
    """Called on shutdown so live gauges stop counting this worker."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.mark_process_dead(os.getpid())
