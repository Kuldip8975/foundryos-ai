"""SQLAlchemy engine and session management.

The engine is created lazily on first use (not at import time), so importing
the application never opens a database connection and tests can substitute
their own engine.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def redacted_database_url(url: str) -> str:
    """Return the URL with its password masked — safe for logs."""
    return make_url(url).render_as_string(hide_password=True)


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_pre_ping=True,  # transparently replace connections dropped by the server
        connect_args={
            "connect_timeout": settings.db_connect_timeout_seconds,
            "application_name": "foundryos-backend",
        },
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session that is always closed.

    Routes/services own their transaction boundaries (``session.commit()``);
    anything not committed is rolled back when the session closes.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
