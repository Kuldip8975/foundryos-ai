"""Readiness checks: database connectivity and migration state.

These run real queries against the configured database. Nothing here
returns a hard-coded success.
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.schemas.health import ComponentCheck, ReadinessResponse

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
READINESS_STATEMENT_TIMEOUT_MS = 2000


@lru_cache
def expected_migration_heads() -> frozenset[str]:
    """Alembic head revision(s) shipped with this build of the application."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return frozenset(ScriptDirectory.from_config(cfg).get_heads())


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _check_migrations(conn: Connection, expected: frozenset[str]) -> ComponentCheck:
    started = time.perf_counter()
    if not inspect(conn).has_table("alembic_version"):
        return ComponentCheck(
            name="migrations",
            status="fail",
            latency_ms=_elapsed_ms(started),
            detail="Migrations have not been applied. Run: alembic upgrade head",
        )
    applied = frozenset(
        row[0] for row in conn.execute(text("SELECT version_num FROM alembic_version"))
    )
    if applied != expected:
        return ComponentCheck(
            name="migrations",
            status="fail",
            latency_ms=_elapsed_ms(started),
            detail=(
                f"Database revision {sorted(applied) or 'none'} does not match "
                f"application head {sorted(expected)}. Run: alembic upgrade head"
            ),
        )
    return ComponentCheck(
        name="migrations",
        status="pass",
        latency_ms=_elapsed_ms(started),
        detail=f"At head {sorted(expected)}",
    )


def check_readiness(engine: Engine, expected_heads: frozenset[str]) -> ReadinessResponse:
    checks: list[ComponentCheck] = []
    started = time.perf_counter()
    try:
        with engine.connect() as conn:
            if conn.dialect.name == "postgresql":
                # Bound the check so a stalled database cannot hang the probe.
                conn.execute(
                    text(f"SET LOCAL statement_timeout = {READINESS_STATEMENT_TIMEOUT_MS}")
                )
            conn.execute(text("SELECT 1")).scalar_one()
            checks.append(
                ComponentCheck(name="database", status="pass", latency_ms=_elapsed_ms(started))
            )
            checks.append(_check_migrations(conn, expected_heads))
    except SQLAlchemyError as exc:
        # Log the error class only: driver messages can include host details.
        logger.warning("readiness check failed", extra={"error_type": type(exc).__name__})
        if not checks:
            checks.append(
                ComponentCheck(
                    name="database",
                    status="fail",
                    latency_ms=_elapsed_ms(started),
                    detail="Database is unreachable or rejected the connection",
                )
            )
            checks.append(
                ComponentCheck(
                    name="migrations", status="skip", detail="Skipped: database unavailable"
                )
            )
        else:
            checks.append(
                ComponentCheck(
                    name="migrations", status="fail", detail="Could not read migration state"
                )
            )

    ready = all(c.status == "pass" for c in checks)
    return ReadinessResponse(status="ready" if ready else "not_ready", checks=checks)
