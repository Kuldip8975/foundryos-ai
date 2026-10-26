from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from app.api.routes.health import engine_dependency, migration_heads_dependency
from app.services.health import expected_migration_heads

HEAD_REVISION = "0005_auth_rbac"
LIVE = "/api/v1/health/live"
READY = "/api/v1/health/ready"


def _apply_revision(engine: Engine, revision: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version VALUES (:rev)"), {"rev": revision})


def _checks(body: dict) -> dict[str, dict]:
    return {c["name"]: c for c in body["checks"]}


def test_alembic_head_is_latest_revision() -> None:
    # Loads the real migration scripts from backend/alembic/versions.
    assert expected_migration_heads() == frozenset({HEAD_REVISION})


def test_liveness_reports_service_identity(client: TestClient) -> None:
    response = client.get(LIVE)
    assert response.status_code == 200
    assert response.json() == {
        "status": "alive",
        "service": "FoundryOS AI",
        "version": "0.1.0",
        "environment": "test",
    }


def test_liveness_does_not_touch_database(app: FastAPI) -> None:
    def fail() -> Engine:
        raise AssertionError("liveness must not request a database engine")

    app.dependency_overrides[engine_dependency] = fail
    with TestClient(app) as client:
        assert client.get(LIVE).status_code == 200


def test_readiness_ready_when_database_is_at_head(
    client: TestClient, sqlite_engine: Engine
) -> None:
    _apply_revision(sqlite_engine, HEAD_REVISION)
    response = client.get(READY)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    checks = _checks(body)
    assert checks["database"]["status"] == "pass"
    assert checks["database"]["latency_ms"] >= 0
    assert checks["migrations"]["status"] == "pass"


def test_readiness_fails_when_migrations_not_applied(client: TestClient) -> None:
    response = client.get(READY)
    assert response.status_code == 503
    checks = _checks(response.json())
    assert checks["database"]["status"] == "pass"
    assert checks["migrations"]["status"] == "fail"
    assert "alembic upgrade head" in checks["migrations"]["detail"]


def test_readiness_fails_on_revision_mismatch(
    app: FastAPI, client: TestClient, sqlite_engine: Engine
) -> None:
    _apply_revision(sqlite_engine, "0001_baseline")
    app.dependency_overrides[migration_heads_dependency] = lambda: frozenset({"0002_future"})
    response = client.get(READY)
    assert response.status_code == 503
    assert _checks(response.json())["migrations"]["status"] == "fail"


def test_readiness_fails_when_database_unreachable(app: FastAPI) -> None:
    # Real PostgreSQL driver, real connection attempt, closed port.
    leak_marker = "s3cr3t-do-not-leak"
    unreachable = create_engine(
        f"postgresql+psycopg://user:{leak_marker}@127.0.0.1:1/nodb",
        connect_args={"connect_timeout": 1},
    )
    app.dependency_overrides[engine_dependency] = lambda: unreachable
    with TestClient(app) as client:
        response = client.get(READY)
    unreachable.dispose()

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    checks = _checks(body)
    assert checks["database"]["status"] == "fail"
    assert checks["migrations"]["status"] == "skip"
    assert leak_marker not in response.text
    assert "127.0.0.1" not in response.text