"""Integration tests against a real PostgreSQL database.

Skipped unless TEST_DATABASE_URL is set in the PROCESS ENVIRONMENT (it is
deliberately not read from .env, so a plain ``pytest`` never touches a
database). Point it at a DEDICATED, disposable, LOCAL test database — these
tests run ``alembic upgrade head`` against it.

Safety gate (``tests/db_target_guard.py``), applied before any engine is
created or migration is run: the URL must use ``postgresql+psycopg://``, the
host must be exactly ``localhost``, ``127.0.0.1`` or ``[::1]``, the database
name must end in ``_test``, and the query string must not override the
host/port/database. Tests receive the URL only through the
``integration_db_url`` fixture, never from the environment directly.

    TEST_DATABASE_URL=postgresql+psycopg://foundryos_app@127.0.0.1:5432/foundryos_test \
        pytest -m integration
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from alembic import command
from app.core.config import get_settings
from app.services.health import check_readiness, expected_migration_heads
from tests.db_target_guard import (
    FORBIDDEN_QUERY_KEYS,
    UnsafeTestDatabaseError,
    validate_test_database_url,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"),
]


def require_safe_test_database_url(raw: str | None) -> str:
    """Return the URL only if it passes the gate; otherwise fail without connecting.

    Pure validation: parses strings only, never creates an engine or connection.
    """
    try:
        target = validate_test_database_url(raw)
    except UnsafeTestDatabaseError as exc:
        pytest.fail(f"Refusing to run integration tests: {exc}", pytrace=False)

    # Defence in depth: SQLAlchemy must parse the URL to the same target, so a
    # parser disagreement can never redirect the connection elsewhere.
    url = make_url(raw.strip())  # type: ignore[union-attr]
    sa_host = (url.host or "").strip("[]").lower()
    overriding = FORBIDDEN_QUERY_KEYS.intersection(k.lower() for k in url.query)
    if sa_host != target.host or url.database != target.database or overriding:
        pytest.fail(
            "Refusing to run integration tests: TEST_DATABASE_URL is parsed "
            "inconsistently; use a plain postgresql+psycopg://user@host:port/name_test URL.",
            pytrace=False,
        )
    return raw.strip()  # type: ignore[union-attr]


@pytest.fixture(scope="module")
def integration_db_url() -> str:
    return require_safe_test_database_url(os.getenv("TEST_DATABASE_URL"))


def test_postgresql_connectivity(integration_db_url: str) -> None:
    engine = create_engine(integration_db_url)
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SHOW server_version")).scalar_one()
        assert version
    finally:
        engine.dispose()


def test_migrations_upgrade_to_head_and_readiness_passes(
    integration_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", integration_db_url)
    get_settings.cache_clear()
    try:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        command.upgrade(cfg, "head")

        engine = create_engine(get_settings().database_url)
        try:
            result = check_readiness(engine, expected_migration_heads())
        finally:
            engine.dispose()
        assert result.status == "ready", result.model_dump()
    finally:
        get_settings.cache_clear()