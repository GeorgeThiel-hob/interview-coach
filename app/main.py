"""FastAPI app factory: web UI (M2/M3), /healthz, background jobs and retention."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine, text
from sqlmodel import Session
from starlette.middleware.sessions import SessionMiddleware

from app.db.session import make_engine
from app.llm.gateway import Gateway, build_gateway
from app.retention import purge_old_runs
from app.settings import Settings, get_settings
from app.web.routes import router

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(
    settings: Settings | None = None,
    gateway: Gateway | None = None,
    engine: Engine | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if not settings.session_secret or not settings.pii_encryption_key:
        raise RuntimeError("SESSION_SECRET and PII_ENCRYPTION_KEY must be set (see .env.example)")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        app.state.engine = engine or make_engine(settings.database_url)
        app.state.gateway = gateway or build_gateway(app.state.engine)
        retention = asyncio.create_task(_retention_loop(app, settings))
        yield
        retention.cancel()
        for job in list(app.state.jobs.values()):
            job.cancel()
        await app.state.gateway.aclose()

    app = FastAPI(title="Interview Coach", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.jobs = {}
    app.state.progress = {}
    app.state.interviews = {}
    app.state.transcriber = None  # tests inject a fake; otherwise faster-whisper, lazily
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        https_only=settings.secure_cookies,
        same_site="lax",
        max_age=14 * 24 * 3600,
        session_cookie="ic_session",
    )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        # everything is self-hosted; Alpine's standard build needs 'unsafe-eval'
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
            "media-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_errors(request: Request, exc: HTTPException) -> Response:
        if exc.status_code == 303 and exc.headers:
            return RedirectResponse(exc.headers["Location"], status_code=303)
        return HTMLResponse(
            f"<h1>{exc.status_code}</h1><p>{exc.detail or ''}</p>", status_code=exc.status_code
        )

    @app.get("/healthz")
    async def healthz(request: Request) -> dict[str, Any]:
        with Session(app.state.engine) as s:
            db_ok = s.exec(text("SELECT 1")).one()[0] == 1  # type: ignore[call-overload]
        local_ok = await app.state.gateway.local_available()
        # "local_model": false means the laptop is off: finished runs work, new runs are blocked
        out: dict[str, Any] = {
            "db": db_ok,
            "local_model": local_ok,
            "new_runs_allowed": db_ok and local_ok,
        }
        token = settings.health_token
        if (
            request.query_params.get("deep")
            and token
            and request.headers.get("x-health-token") == token
        ):
            out["providers"] = await app.state.gateway.health()
        return out

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(router)
    return app


async def _retention_loop(app: FastAPI, settings: Settings) -> None:
    while True:
        with contextlib.suppress(Exception):
            removed = await asyncio.to_thread(
                purge_old_runs, app.state.engine, settings.retention_days
            )
            if removed:
                log.info(
                    "retention: removed %d runs older than %d days",
                    removed,
                    settings.retention_days,
                )
        await asyncio.sleep(6 * 3600)


def app_factory() -> FastAPI:
    """Entry point for uvicorn: ``uvicorn app.main:app_factory --factory``."""
    return create_app()
