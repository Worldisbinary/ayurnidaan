"""Application factory for the clinical API.  Run: ``uvicorn ayurnidaan.app.main:app``."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .. import __version__
from ..config import Settings, get_settings
from ..logging_utils import get_logger
from .db import Base, Database
from .routers import admin, auth, encounters, knowledge, me, practitioner
from .services import ClinicalService

log = get_logger(__name__)
API_PREFIX = "/api/v1"


class RateLimiter:
    """Sliding-window limit per client IP (and a tighter one for auth endpoints).

    In-process: correct for a single instance. Behind several replicas, move this to the
    gateway or Redis - the limits then apply per replica.
    """

    def __init__(self, per_minute: int, auth_per_minute: int = 10):
        self.limits = {"auth": auth_per_minute, "api": per_minute}
        self.hits: dict[tuple[str, str], deque] = defaultdict(deque)

    def allow(self, ip: str, bucket: str) -> bool:
        now, window = time.monotonic(), self.hits[(ip, bucket)]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.limits[bucket]:
            return False
        window.append(now)
        return True


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.check_production()
    db = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.environment != "production":
            Base.metadata.create_all(db.engine)  # production schema is owned by Alembic
        with db.SessionLocal() as s:
            app.state.clinical.load_active(s)
        log.info(
            "startup",
            fields={"env": settings.environment, "engine": app.state.clinical.engine.version},
        )
        yield

    app = FastAPI(
        title="Ayurnidaan Clinical API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
    )
    app.state.settings, app.state.db = settings, db
    app.state.clinical = ClinicalService(settings)
    limiter = RateLimiter(settings.rate_limit_per_minute)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        ip = request.client.host if request.client else "unknown"
        bucket = (
            "auth"
            if request.url.path.startswith(f"{API_PREFIX}/auth/") and request.method == "POST"
            else "api"
        )
        if settings.environment != "test" and not limiter.allow(ip, bucket):
            return JSONResponse(
                {"detail": "too many requests"}, status_code=429, headers={"Retry-After": "60"}
            )
        t = time.perf_counter()
        response = await call_next(request)
        response.headers.update(
            {
                "X-Request-ID": rid,
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
                "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            }
        )
        # Never log bodies or query strings: they can contain health data.
        log.info(
            "http",
            fields={
                "rid": rid,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - t) * 1000, 1),
            },
        )
        return response

    for r in (
        auth.router,
        me.router,
        encounters.router,
        practitioner.router,
        admin.router,
        knowledge.router,
    ):
        app.include_router(r, prefix=API_PREFIX)

    @app.get("/health", tags=["ops"])
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/ready", tags=["ops"])
    def ready() -> JSONResponse:
        try:
            with db.engine.connect() as c:
                c.execute(text("SELECT 1"))
            ok = {"database": True, "knowledge_pack": app.state.clinical.pack.version}
            return JSONResponse(ok)
        except Exception as exc:
            return JSONResponse({"database": False, "error": type(exc).__name__}, status_code=503)

    return app


def __getattr__(name: str):  # lazy module-level `app` for uvicorn without import-time side effects
    if name == "app":
        return create_app()
    raise AttributeError(name)
