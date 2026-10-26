"""FastAPI application entry point.

Run locally:  uvicorn app.main:app --reload   (from the backend/ directory)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import get_engine, redacted_database_url
from app.services.auth.rate_limit import SlidingWindowLimiter

logger = logging.getLogger("app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "starting application",
            extra={
                "environment": settings.environment,
                "version": settings.app_version,
                "database": redacted_database_url(settings.database_url),
                "cors_origins": settings.cors_origins,
            },
        )
        yield
        # Release pooled connections only if the engine was ever created.
        if get_engine.cache_info().currsize:
            get_engine().dispose()
        logger.info("application stopped")

    docs = settings.enable_api_docs
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json" if docs else None,
    )

    # Middleware order: last added runs first. CORS must wrap everything so
    # error responses also carry CORS headers.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # Sessions use a bearer token, not cookies, so credentials are never needed
        # (and cross-site request forgery does not apply).
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    app.state.settings = settings
    app.state.login_limiter = SlidingWindowLimiter(
        attempts=settings.auth_rate_limit_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()