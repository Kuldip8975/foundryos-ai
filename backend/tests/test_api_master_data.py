"""Machines, products and defect categories API."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from tests.helpers import API, error_code, post

# (path, business-key field)
RESOURCES = [
    ("/machines", "code"),
    ("/products", "part_number"),
    ("/defect-categories", "code"),
]


def _create(api: TestClient, path: str, key: str, value: str, **extra: object) -> dict:
    return post(api, path, {key: value, "name": f"Name {value}", **extra})


@pytest.mark.parametrize(("path", "key"), RESOURCES)
def test_create_and_get(api: TestClient, path: str, key: str) -> None:
    created = _create(api, path, key, "AB-01", description="First")
    assert created[key] == "AB-01"
    assert created["is_active"] is True
    assert created["data_source"] == "manual"
    assert datetime.fromisoformat(created["created_at"]).utcoffset().total_seconds() == 0

    fetched = api.get(f"{API}{path}/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created


@pytest.mark.parametrize(("path", "key"), RESOURCES)
def test_duplicate_business_key_is_a_conflict(api: TestClient, path: str, key: str) -> None:
    _create(api, path, key, "DUP-1")
    response = api.post(f"{API}{path}", json={key: "DUP-1", "name": "Again"})
    assert response.status_code == 409
    assert error_code(response) == "conflict"


@pytest.mark.parametrize(("path", "key"), RESOURCES)
@pytest.mark.parametrize(
    "payload_update",
    [
        {"name": ""},                     # blank name
        {"CODE_PLACEHOLDER": "bad code"},  # space not allowed in identifiers
        {"CODE_PLACEHOLDER": "-leading"},  # must start with a letter or digit
        {"unexpected": "field"},           # unknown fields are rejected
        {"is_active": "maybe"},
    ],
)
def test_invalid_create_payloads_are_rejected(
    api: TestClient, path: str, key: str, payload_update: dict[str, object]
) -> None:
    payload: dict[str, object] = {key: "OK-1", "name": "Valid"}
    for field, value in payload_update.items():
        payload[key if field == "CODE_PLACEHOLDER" else field] = value
    response = api.post(f"{API}{path}", json=payload)
    assert response.status_code == 422
    assert error_code(response) == "validation_error"


@pytest.mark.parametrize(("path", "key"), RESOURCES)
def test_update_changes_only_sent_fields(api: TestClient, path: str, key: str) -> None:
    created = _create(api, path, key, "UP-1", description="Keep me")
    response = api.patch(
        f"{API}{path}/{created['id']}", json={"name": "Renamed", "is_active": False}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed"
    assert body["is_active"] is False
    assert body["description"] == "Keep me"
    assert body[key] == "UP-1"


@pytest.mark.parametrize(("path", "key"), RESOURCES)
def test_business_key_is_immutable_and_nulls_rejected(api: TestClient, path: str, key: str) -> None:
    created = _create(api, path, key, "IM-1")
    url = f"{API}{path}/{created['id']}"
    assert api.patch(url, json={key: "IM-2"}).status_code == 422
    response = api.patch(url, json={"name": None})
    assert response.status_code == 422
    assert error_code(response) == "validation_error"
    # description is nullable and can be cleared
    assert api.patch(url, json={"description": None}).status_code == 200


@pytest.mark.parametrize(("path", "key"), RESOURCES)
def test_missing_and_out_of_range_ids(api: TestClient, path: str, key: str) -> None:
    missing = api.get(f"{API}{path}/999")
    assert missing.status_code == 404
    assert error_code(missing) == "not_found"
    assert api.get(f"{API}{path}/0").status_code == 422
    assert api.get(f"{API}{path}/99999999999999999999").status_code == 422
    assert api.patch(f"{API}{path}/999", json={"name": "x"}).status_code == 404


def test_list_paginates_with_stable_order_and_total(api: TestClient) -> None:
    ids = [_create(api, "/machines", "code", f"PG-{i}")["id"] for i in range(5)]
    page = api.get(f"{API}/machines", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 5
    assert page["limit"] == 2
    assert page["offset"] == 2
    assert [m["id"] for m in page["items"]] == ids[2:4]

    beyond = api.get(f"{API}/machines", params={"offset": 10}).json()
    assert beyond["items"] == []
    assert beyond["total"] == 5


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
def test_invalid_pagination_is_rejected(api: TestClient, params: dict[str, int]) -> None:
    response = api.get(f"{API}/machines", params=params)
    assert response.status_code == 422
    assert error_code(response) == "validation_error"


def test_list_filters_by_active_flag_and_search(api: TestClient) -> None:
    _create(api, "/products", "part_number", "BRK-100", name="Bracket")
    housing = _create(api, "/products", "part_number", "HSG-200", name="Housing")
    api.patch(f"{API}/products/{housing['id']}", json={"is_active": False})

    active = api.get(f"{API}/products", params={"is_active": True}).json()
    assert [p["part_number"] for p in active["items"]] == ["BRK-100"]

    by_name = api.get(f"{API}/products", params={"q": "hous"}).json()
    assert [p["part_number"] for p in by_name["items"]] == ["HSG-200"]

    by_key = api.get(f"{API}/products", params={"q": "brk"}).json()
    assert by_key["total"] == 1

    # LIKE wildcards in the search term are matched literally
    assert api.get(f"{API}/products", params={"q": "%"}).json()["total"] == 0

    assert api.get(f"{API}/products", params={"data_source": "synthetic"}).json()["total"] == 0
    assert api.get(f"{API}/products", params={"data_source": "bogus"}).status_code == 422