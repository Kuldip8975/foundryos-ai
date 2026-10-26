from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from app.core.errors import NotFoundError


def _add_probe_routes(app: FastAPI) -> None:
    """Routes that exist only in tests, to exercise the error handlers."""

    @app.get("/_test/boom")
    def boom() -> None:
        raise RuntimeError("internal detail that must not leak")

    @app.get("/_test/validate")
    def validate(limit: int = Query(ge=1, le=10)) -> dict[str, int]:
        return {"limit": limit}

    @app.get("/_test/app-error")
    def app_error() -> None:
        raise NotFoundError("Production line not found")


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["x-request-id"]


def test_validation_error_envelope_omits_input_values(app: FastAPI) -> None:
    _add_probe_routes(app)
    with TestClient(app) as client:
        response = client.get("/_test/validate", params={"limit": "999"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["loc"] == ["query", "limit"]
    assert "input" not in error["details"][0]


def test_app_error_maps_to_status_and_code(app: FastAPI) -> None:
    _add_probe_routes(app)
    with TestClient(app) as client:
        response = client.get("/_test/app-error")
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Production line not found"


def test_unhandled_exception_returns_generic_500(app: FastAPI) -> None:
    _add_probe_routes(app)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_test/boom")
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert "must not leak" not in response.text
    assert error["request_id"] == response.headers["x-request-id"]


def test_safe_incoming_request_id_is_propagated(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"X-Request-ID": "demo-123"})
    assert response.headers["x-request-id"] == "demo-123"


def test_unsafe_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"X-Request-ID": "bad id\twith spaces"})
    assert response.headers["x-request-id"] != "bad id\twith spaces"
    assert len(response.headers["x-request-id"]) == 32


def test_cors_allows_configured_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health/live",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_rejects_unlisted_origin(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers
