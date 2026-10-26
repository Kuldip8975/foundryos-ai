"""Small helpers for API tests (not a test module)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

API = "/api/v1"


def post(api: TestClient, path: str, payload: dict[str, Any], expected: int = 201) -> dict:
    response = api.post(f"{API}{path}", json=payload)
    assert response.status_code == expected, response.text
    return response.json()


def error_code(response: Any) -> str:
    body = response.json()
    assert set(body) == {"error"}, body
    return body["error"]["code"]


def machine(api: TestClient, code: str = "M-01", **overrides: Any) -> dict:
    return post(api, "/machines", {"code": code, "name": f"Machine {code}", **overrides})


def product(api: TestClient, part_number: str = "P-1001", **overrides: Any) -> dict:
    return post(
        api, "/products", {"part_number": part_number, "name": f"Part {part_number}", **overrides}
    )


def defect_category(api: TestClient, code: str = "DIM", **overrides: Any) -> dict:
    return post(api, "/defect-categories", {"code": code, "name": f"Defect {code}", **overrides})


def production_payload(product_id: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "production_date": "2026-01-10",
        "shift": "A",
        "product_id": product_id,
        "target_quantity": 100,
        "actual_quantity": 95,
        "accepted_quantity": 90,
        "rejected_quantity": 5,
    }
    payload.update(overrides)
    return payload


def production_record(api: TestClient, product_id: int, **overrides: Any) -> dict:
    return post(api, "/production-records", production_payload(product_id, **overrides))