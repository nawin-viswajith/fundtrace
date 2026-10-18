"""FastAPI application: REST API + the built React app, on one Cloud Run service."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import telemetry
from app import crypto
from app.api import auth, cases, ingest, ops, overview, portal
from app.config import get_settings
from app.db import create_all, init_engine, session_scope

log = logging.getLogger("fundtrace")
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
CODES = {400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found", 409: "conflict", 413: "too_large",
         410: "gone", 415: "unsupported_media", 422: "invalid_input", 429: "rate_limited", 500: "internal_error"}


def bootstrap() -> None:
    s = get_settings()
    crypto.keyring()  # fail fast if field-encryption keys are missing or wrong
    init_engine(s.database_url)
    create_all()
    from app.seed.loader import ensure_customer_users, ensure_users, is_seeded, seed

    from sqlalchemy import text

    with session_scope() as db:
        mysql = db.get_bind().dialect.name == "mysql"
        if mysql:  # several Cloud Run instances may start together: only one seeds
            db.execute(text("SELECT GET_LOCK('fundtrace_bootstrap', 60)"))
        try:
            ensure_users(db)
            if s.seed_on_start and not is_seeded(db):
                info = seed(db)
                log.info("synthetic demo data seeded: %s cases", info["cases"])
            ensure_customer_users(db)  # existing deployments get the portal logins too
            crypto.backfill(db)  # rows written before field encryption was enabled
            db.commit()
        finally:
            if mysql:
                db.execute(text("SELECT RELEASE_LOCK('fundtrace_bootstrap')"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    telemetry.setup(s.otel_exporter, s.gcp_project, s.log_level)
    bootstrap()
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="FundTrace API", version="1.0.0", lifespan=lifespan,
                  description="AI-assisted dispute investigation on synthetic data. Signals are for review, never verdicts.")
    if s.environment == "local":
        app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",")], allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        elif request.url.path.startswith("/assets/"):
            # file names carry a content hash, so they never change: cache them for a year
            resp.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        return resp

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse({"error": {"code": CODES.get(exc.status_code, "error"), "message": str(exc.detail)}}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        fields = sorted({".".join(str(p) for p in e.get("loc", [])[1:]) or "body" for e in exc.errors()})
        return JSONResponse({"error": {"code": "invalid_input", "message": "Invalid input", "fields": fields}}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse({"error": {"code": "internal_error", "message": "Something went wrong. The error was logged."}}, status_code=500)

    app.include_router(auth.router)
    app.include_router(cases.router)
    app.include_router(ops.router)
    app.include_router(overview.router)
    app.include_router(ingest.router)
    app.include_router(portal.router)

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="/api/healthz,/assets/.*")
    except Exception as exc:  # pragma: no cover
        log.warning("FastAPI instrumentation unavailable: %s", exc)

    if FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "Not found")
            f = FRONTEND_DIST / path
            if path and f.is_file() and FRONTEND_DIST in f.resolve().parents:
                return FileResponse(f)
            # The app shell must always be revalidated, or a browser keeps showing an old release after a deploy.
            return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
