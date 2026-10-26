"""Shared test fixtures.

Unit tests never need a running PostgreSQL server:
* liveness/error/config tests don't touch the database at all;
* readiness logic runs against a real in-memory SQLite engine;
* the "database down" case uses a real PostgreSQL URL pointing at a closed port;
* manufacturing-data tests (Module 1) use a fresh in-memory SQLite database per
  test, built from the ORM metadata, with foreign keys enforced.

Tests marked ``integration`` use a real PostgreSQL database (TEST_DATABASE_URL).

Authentication (Module 5): the ``api`` client used by the Module 1–4 tests
stands in for a signed-in person with every permission and no machine scope,
so those tests keep exercising business rules. Sign-in, permissions, data
scope and forbidden access are tested through ``secured_api``, which uses the
real authentication dependencies.
"""

from __future__ import annotations

import os

# app.main builds a module-level app at import time, which requires a
# DATABASE_URL. Provide a harmless placeholder; no connection is opened.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://placeholder:placeholder@127.0.0.1:1/placeholder")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, create_engine, event  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.auth import get_principal  # noqa: E402
from app.api.routes.health import engine_dependency  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.passwords import ScryptParams, set_hash_params  # noqa: E402
from app.core.permissions import Permission  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.services.auth.sessions import Principal  # noqa: E402

# Cheap password hashing keeps the suite fast; production uses the OWASP cost.
set_hash_params(ScryptParams(log2_n=10, r=8, p=1))


class HarnessPrincipal(Principal):
    """Test-only stand-in: every permission, every machine."""

    @property
    def permissions(self) -> frozenset[Permission]:
        return frozenset(Permission)


HARNESS_PRINCIPAL = HarnessPrincipal(
    user_id=0,
    username="test-harness",
    display_name="Test harness",
    role=UserRole.SUPERVISOR,
    session_id=None,
    must_change_password=False,
    machine_ids=None,
)


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://test:test-password@127.0.0.1:1/foundryos_test",
        "environment": "test",
        "log_format": "console",
        "log_level": "WARNING",
        "cors_allowed_origins": "http://localhost:5173",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type, call-arg]


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def sqlite_engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    yield engine
    engine.dispose()


@pytest.fixture
def app(settings: Settings, sqlite_engine: Engine) -> FastAPI:
    application = create_app(settings)
    application.dependency_overrides[engine_dependency] = lambda: sqlite_engine
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _enable_sqlite_foreign_keys(dbapi_connection: object, _record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_sqlite_engine() -> Engine:
    """Isolated in-memory database (one shared connection) with FK enforcement."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


@pytest.fixture
def data_engine() -> Iterator[Engine]:
    engine = make_sqlite_engine()
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(data_engine: Engine) -> Iterator[Session]:
    with Session(data_engine, expire_on_commit=False) as session:
        yield session


def _use_test_database(app: FastAPI, data_engine: Engine) -> None:
    factory = sessionmaker(bind=data_engine, autoflush=False, expire_on_commit=False)

    def _get_test_db() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_test_db


@pytest.fixture
def api(app: FastAPI, data_engine: Engine) -> Iterator[TestClient]:
    """Client whose requests use the isolated manufacturing-data database.

    Requests act as :data:`HARNESS_PRINCIPAL` (see the module docstring).
    """
    _use_test_database(app, data_engine)
    app.dependency_overrides[get_principal] = lambda: HARNESS_PRINCIPAL
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def secured_api(app: FastAPI, data_engine: Engine) -> Iterator[TestClient]:
    """Like ``api`` but with real sign-in and permission checks."""
    _use_test_database(app, data_engine)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client