"""Application factory for the clinical API.  Run: ``uvicorn ayurnidaan.app.main:app``.

Request path through this file (docs/SYSTEM_DESIGN.md has the full picture):

    nginx / Render edge -> CORS -> ``edge`` middleware: request ID, rate limit,
    metrics, security headers, access log -> router -> handler -> DB / engine
"""

from __future__ import annotations

import hmac
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .. import __version__
from ..config import Settings, get_settings
from ..logging_utils import get_logger, request_id_var
from . import observability as obs
from .cache import TTLCache
from .db import Base, Database
from .ratelimit import TokenBucketLimiter, client_ip
from .routers import admin, auth, ayurveda, encounters, knowledge, me, practitioner
from .services import ClinicalService

log = get_logger(__name__)
API_PREFIX = "/api/v1"
OPS_PATHS = ("/healthz", "/readyz", "/health", "/ready", "/metrics")
EXPOSED_HEADERS = [
    "X-Request-ID",
    "X-Next-Cursor",
    "Retry-After",
    "Idempotent-Replayed",
    "RateLimit-Limit",
    "RateLimit-Remaining",
]


def _commit() -> str:
    # Render injects RENDER_GIT_COMMIT; the Docker build bakes AYUR_GIT_SHA. CD polls
    # /health until the deployed commit matches the one it just shipped.
    return os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("AYUR_GIT_SHA") or "dev"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.check_production()
    db = Database(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.environment != "production":
            Base.metadata.create_all(db.engine)  # production schema is owned by Alembic
        with db.SessionLocal() as s:
            app.state.clinical.load_active(s)
        obs.BUILD_INFO.labels(__version__, _commit(), app.state.clinical.pack.version).set(1)
        app.state.ready = True
        log.info(
            "startup",
            fields={"env": settings.environment, "engine": app.state.clinical.engine.version},
        )
        yield
        # Draining: /readyz turns 503 so the load balancer stops sending new requests
        # while in-flight ones finish.
        app.state.ready = False
        obs.mark_worker_dead()
        db.engine.dispose()

    app = FastAPI(
        title="Ayurnidaan Clinical API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )
    app.state.settings, app.state.db, app.state.ready = settings, db, False
    app.state.clinical = ClinicalService(settings)
    app.state.geo_cache = TTLCache("geocode", maxsize=1024, ttl_seconds=24 * 3600)
    app.state.search_cache = TTLCache("symptom_search", maxsize=4096, ttl_seconds=None)
    limiter = TokenBucketLimiter(
        {"api": settings.rate_limit_per_minute, "auth": settings.auth_rate_limit_per_minute}
    )
    app.state.limiter = limiter

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "If-None-Match"],
        expose_headers=EXPOSED_HEADERS,
        max_age=7200,  # browsers cache preflights for up to 2 h (Chromium's cap)
    )

    @app.middleware("http")
    async def edge(request: Request, call_next):
        rid = obs.resolve_request_id(request.headers.get("X-Request-ID"))
        token = request_id_var.set(rid)
        try:
            return await _handle(request, call_next, rid)
        finally:
            request_id_var.reset(token)

    async def _handle(request: Request, call_next, rid: str) -> Response:
        path = request.url.path
        bucket = (
            "auth" if path.startswith(f"{API_PREFIX}/auth/") and request.method == "POST" else "api"
        )
        # CORS preflights are answered by CORSMiddleware without touching the app. Counting
        # them would double every browser call's cost (search-as-you-type preflights each new
        # URL), and a 429 here would also lack CORS headers and surface as a CORS error.
        preflight = (
            request.method == "OPTIONS" and "access-control-request-method" in request.headers
        )
        limited = settings.environment != "test" and not preflight and path not in OPS_PATHS
        decision = None
        if limited:
            ip = client_ip(
                request.client.host if request.client else None,
                request.headers.get("x-forwarded-for"),
                settings.trusted_proxy_hops,
            )
            decision = limiter.check(ip, bucket)
            if not decision.allowed:
                obs.RATE_LIMITED.labels(bucket).inc()
                obs.HTTP_REQUESTS.labels(request.method, "<rate-limited>", "429").inc()
                retry = max(1, round(decision.retry_after))
                return JSONResponse(
                    {"detail": "too many requests"},
                    status_code=429,
                    headers={
                        "Retry-After": str(retry),
                        "RateLimit-Limit": str(decision.limit),
                        "RateLimit-Remaining": "0",
                        "X-Request-ID": rid,
                    },
                )

        t = time.perf_counter()
        obs.HTTP_IN_PROGRESS.inc()
        try:
            response = await call_next(request)
        except Exception as exc:
            route = getattr(request.scope.get("route"), "path", "<unmatched>")
            obs.HTTP_EXCEPTIONS.labels(route, type(exc).__name__).inc()
            obs.HTTP_REQUESTS.labels(request.method, route, "500").inc()
            log.exception("unhandled", fields={"method": request.method, "route": route})
            raise
        finally:
            obs.HTTP_IN_PROGRESS.dec()
            obs.DB_POOL_CHECKED_OUT.set(db.checked_out())
        elapsed = time.perf_counter() - t
        # Label by route template, never raw path: bounded cardinality.
        route = getattr(request.scope.get("route"), "path", "<unmatched>")
        obs.HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        obs.HTTP_LATENCY.labels(request.method, route).observe(elapsed)

        response.headers.update(
            {
                "X-Request-ID": rid,
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Cross-Origin-Resource-Policy": "cross-origin",
            }
        )
        # Health data must never sit in a shared cache. Public reference endpoints opt in
        # to caching explicitly (pagination.cached_json); everything else is no-store.
        response.headers.setdefault("Cache-Control", "no-store")
        if decision is not None:
            response.headers["RateLimit-Limit"] = str(decision.limit)
            response.headers["RateLimit-Remaining"] = str(decision.remaining)
        # A JSON API never needs to load anything; the dev-only /docs page needs its CDN.
        # A route that serves HTML (the DigiLocker sandbox page) sets its own, narrower policy.
        if not path.startswith(("/docs", "/redoc")):
            response.headers.setdefault(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
        # Never log bodies or query strings: they can contain health data.
        log.info(
            "http",
            fields={
                "method": request.method,
                "route": route,
                "path": path,
                "status": response.status_code,
                "ms": round(elapsed * 1000, 1),
            },
        )
        return response

    for r in (
        auth.router,
        me.router,
        encounters.router,
        ayurveda.router,
        practitioner.router,
        admin.router,
        knowledge.router,
    ):
        app.include_router(r, prefix=API_PREFIX)

    # --- operations endpoints -------------------------------------------------------------
    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        """Liveness: the process is up and serving. No dependency checks, so a database
        outage never makes the orchestrator restart healthy API processes in a loop."""
        return {"status": "ok", "version": __version__, "commit": _commit()}

    @app.get("/readyz", tags=["ops"])
    def readyz() -> JSONResponse:
        """Readiness: safe to send traffic (database reachable, knowledge pack loaded,
        not shutting down). Load balancers route around a 503 instead of restarting."""
        if not app.state.ready:
            return JSONResponse({"ready": False, "reason": "starting or draining"}, 503)
        try:
            with db.engine.connect() as c:
                c.execute(text("SELECT 1"))
        except Exception as exc:
            return JSONResponse(
                {"ready": False, "database": False, "error": type(exc).__name__}, 503
            )
        return JSONResponse(
            {
                "ready": True,
                "database": True,
                "knowledge_pack": app.state.clinical.pack.version,
                "engine": app.state.clinical.engine.version,
            }
        )

    # Older names, kept because deploy hooks and smoke tests already poll them.
    app.add_api_route("/health", healthz, methods=["GET"], include_in_schema=False)
    app.add_api_route("/ready", readyz, methods=["GET"], include_in_schema=False)

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request) -> Response:
        """Prometheus exposition. Bearer token when configured; off in production without one."""
        if settings.metrics_token:
            given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(given, settings.metrics_token):
                return JSONResponse({"detail": "unauthorized"}, 401)
        elif settings.environment == "production":
            return JSONResponse({"detail": "Not Found"}, 404)
        payload, content_type = obs.metrics_payload()
        return Response(payload, media_type=content_type)

    return app


def __getattr__(name: str):  # lazy module-level `app` for uvicorn without import-time side effects
    if name == "app":
        return create_app()
    raise AttributeError(name)
