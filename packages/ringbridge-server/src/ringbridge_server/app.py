"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ringbridge_server import __version__
from ringbridge_server.api import agents, calls
from ringbridge_server.db import make_engine, make_sessionmaker
from ringbridge_server.migrate import head_revision
from ringbridge_server.settings import Settings, get_settings

log = logging.getLogger("ringbridge.server")

READY_TIMEOUT_S = 2.0


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        log.info("server starting", extra={"version": __version__})
        yield
        await engine.dispose()

    app = FastAPI(
        title="Ringbridge control plane",
        version=__version__,
        summary="Agents, phone numbers, calls and their history.",
        license_info={"name": "Apache-2.0", "identifier": "Apache-2.0"},
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.schema_head = head_revision()

    app.middleware("http")(_request_context)
    app.add_exception_handler(agents.SpecRejectedError, agents.spec_rejected_handler)
    app.include_router(agents.router)
    app.include_router(calls.public)
    app.include_router(calls.internal)

    @app.get("/healthz", tags=["ops"], summary="Liveness: the process is up")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get(
        "/readyz",
        tags=["ops"],
        summary="Readiness: the database answers and its schema is up to date",
        responses={503: {"description": "Not ready"}},
    )
    async def readyz() -> JSONResponse:
        expected: str = app.state.schema_head
        try:
            async with asyncio.timeout(READY_TIMEOUT_S), engine.connect() as conn:
                current = await conn.scalar(text("SELECT version_num FROM alembic_version"))
        except Exception as e:  # any failure means "not ready"; the reason is in the body
            log.warning("readiness check failed", extra={"error": type(e).__name__})
            return _not_ready(f"database unavailable ({type(e).__name__})")
        if current != expected:
            return _not_ready(f"schema at {current}, expected {expected}: run migrations")
        return JSONResponse({"status": "ready", "schema": current})

    return app


def _not_ready(reason: str) -> JSONResponse:
    return JSONResponse(
        {"status": "not_ready", "reason": reason},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


async def _request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Give every request an id (kept if the caller sent one) and log one line per request."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    if request.url.path not in ("/healthz", "/readyz"):
        log.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )
    return response
