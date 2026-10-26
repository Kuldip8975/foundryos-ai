"""Production records and quality inspections API."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tests.helpers import (
    API,
    defect_category,
    error_code,
    machine,
    post,
    product,
    production_payload,
    production_record,
)

# --------------------------------------------------------------------------- production records


def test_create_production_record(api: TestClient) -> None:
    part = product(api)
    press = machine(api)
    record = production_record(api, part["id"], machine_id=press["id"], notes="Night run")
    assert record["product_id"] == part["id"]
    assert record["machine_id"] == press["id"]
    assert record["pending_quantity"] == 0  # 95 - 90 - 5
    assert record["data_source"] == "manual"
    assert record["external_ref"] is None


def test_pending_quantity_allows_units_awaiting_inspection(api: TestClient) -> None:
    part = product(api)
    record = production_record(api, part["id"], accepted_quantity=80, rejected_quantity=5)
    assert record["pending_quantity"] == 10


def test_inconsistent_quantities_are_rejected(api: TestClient) -> None:
    part = product(api)
    response = api.post(
        f"{API}/production-records",
        json=production_payload(part["id"], accepted_quantity=93, rejected_quantity=5),
    )
    assert response.status_code == 422
    assert error_code(response) == "inconsistent_quantities"


@pytest.mark.parametrize(
    "overrides",
    [
        {"actual_quantity": -1},
        {"target_quantity": "100"},  # strict integers: strings rejected
        {"rejected_quantity": 2.5},
        {"accepted_quantity": True},
        {"shift": ""},
        {"shift": "night shift"},  # spaces not allowed in shift codes
        {"production_date": "10/01/2026"},
        {"product_id": 0},
        {"data_source": "synthetic"},  # provenance is never client-controlled
    ],
)
def test_invalid_production_fields_are_rejected(
    api: TestClient, overrides: dict[str, object]
) -> None:
    part = product(api)
    payload = production_payload(part["id"])
    payload.update(overrides)  # may replace product_id itself
    response = api.post(f"{API}/production-records", json=payload)
    assert response.status_code == 422
    assert error_code(response) == "validation_error"


def test_references_must_exist_and_be_active(api: TestClient) -> None:
    part = product(api)
    unknown = api.post(f"{API}/production-records", json=production_payload(999))
    assert unknown.status_code == 422
    assert error_code(unknown) == "invalid_reference"
    assert unknown.json()["error"]["details"] == [{"field": "product_id"}]

    bad_machine = api.post(
        f"{API}/production-records", json=production_payload(part["id"], machine_id=999)
    )
    assert error_code(bad_machine) == "invalid_reference"

    api.patch(f"{API}/products/{part['id']}", json={"is_active": False})
    inactive = api.post(f"{API}/production-records", json=production_payload(part["id"]))
    assert inactive.status_code == 422
    assert error_code(inactive) == "inactive_reference"


def test_future_production_date_is_rejected(api: TestClient) -> None:
    part = product(api)
    future = (datetime.now(UTC).date() + timedelta(days=3)).isoformat()
    response = api.post(
        f"{API}/production-records", json=production_payload(part["id"], production_date=future)
    )
    assert response.status_code == 422
    assert error_code(response) == "future_date"


def test_duplicate_external_ref_is_a_conflict(api: TestClient) -> None:
    part = product(api)
    production_record(api, part["id"], external_ref="ERP-1")
    response = api.post(
        f"{API}/production-records", json=production_payload(part["id"], external_ref="ERP-1")
    )
    assert response.status_code == 409
    assert error_code(response) == "conflict"


def test_list_filters_and_pagination(api: TestClient) -> None:
    part_a, part_b = product(api, "P-A"), product(api, "P-B")
    mill = machine(api, "MILL")
    for day in (5, 6, 7, 8):
        production_record(api, part_a["id"], production_date=f"2026-01-0{day}", shift="A")
    production_record(api, part_b["id"], production_date="2026-01-06", shift="B",
                      machine_id=mill["id"])

    def query(**params: object) -> dict:
        response = api.get(f"{API}/production-records", params=params)
        assert response.status_code == 200, response.text
        return response.json()

    everything = query()
    assert everything["total"] == 5
    dates = [r["production_date"] for r in everything["items"]]
    assert dates == sorted(dates, reverse=True)  # newest first

    window = query(date_from="2026-01-06", date_to="2026-01-07")
    assert window["total"] == 3
    assert query(shift="B")["total"] == 1
    assert query(product_id=part_b["id"])["total"] == 1
    assert query(machine_id=mill["id"])["total"] == 1
    assert query(product_id=part_a["id"], date_from="2026-01-08")["total"] == 1

    page = query(limit=2, offset=1)
    assert page["total"] == 5
    assert [r["id"] for r in page["items"]] == [r["id"] for r in everything["items"][1:3]]


def test_impossible_date_range_is_rejected(api: TestClient) -> None:
    response = api.get(
        f"{API}/production-records", params={"date_from": "2026-01-08", "date_to": "2026-01-01"}
    )
    assert response.status_code == 422
    assert error_code(response) == "invalid_date_range"


def test_update_revalidates_merged_quantities(api: TestClient) -> None:
    part = product(api)
    record = production_record(api, part["id"])
    url = f"{API}/production-records/{record['id']}"

    bad = api.patch(url, json={"rejected_quantity": 10})  # 90 + 10 > 95
    assert bad.status_code == 422
    assert error_code(bad) == "inconsistent_quantities"

    good = api.patch(url, json={"actual_quantity": 100, "rejected_quantity": 10})
    assert good.status_code == 200
    assert good.json()["pending_quantity"] == 0

    assert api.patch(url, json={"shift": None}).status_code == 422
    unchanged = api.get(url).json()
    assert unchanged["rejected_quantity"] == 10


def test_actual_quantity_cannot_drop_below_an_inspection(api: TestClient) -> None:
    part = product(api)
    record = production_record(api, part["id"], actual_quantity=95)
    post(api, "/quality-inspections", {
        "production_record_id": record["id"], "inspected_at": "2026-01-10T08:00:00Z",
        "inspected_quantity": 60, "defect_quantity": 0,
    })
    response = api.patch(
        f"{API}/production-records/{record['id']}",
        json={"actual_quantity": 50, "accepted_quantity": 45, "rejected_quantity": 5},
    )
    assert response.status_code == 422
    assert error_code(response) == "inconsistent_quantities"


# --------------------------------------------------------------------------- quality inspections


@pytest.fixture
def record(api: TestClient) -> dict:
    return production_record(api, product(api)["id"])


def _inspection(record_id: int, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "production_record_id": record_id,
        "inspected_at": "2026-01-10T14:30:00+05:30",
        "inspected_quantity": 50,
        "defect_quantity": 0,
    }
    payload.update(overrides)
    return payload


def test_create_inspection_stores_utc(api: TestClient, record: dict) -> None:
    created = post(api, "/quality-inspections", _inspection(record["id"]))
    stored = datetime.fromisoformat(created["inspected_at"])
    assert stored == datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
    assert stored.utcoffset() == timedelta(0)


def test_defects_require_a_category(api: TestClient, record: dict) -> None:
    response = api.post(
        f"{API}/quality-inspections", json=_inspection(record["id"], defect_quantity=3)
    )
    assert response.status_code == 422
    assert error_code(response) == "defect_category_required"

    category = defect_category(api)
    created = post(
        api, "/quality-inspections",
        _inspection(record["id"], defect_quantity=3, defect_category_id=category["id"]),
    )
    assert created["defect_category_id"] == category["id"]


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"defect_quantity": 51, "defect_category_id": None}, "inconsistent_quantities"),
        ({"inspected_quantity": 96}, "inconsistent_quantities"),  # record actual is 95
        ({"production_record_id": 999}, "invalid_reference"),
        ({"defect_quantity": 1, "defect_category_id": 999}, "invalid_reference"),
    ],
)
def test_inspection_business_rules(
    api: TestClient, record: dict, overrides: dict[str, object], code: str
) -> None:
    response = api.post(f"{API}/quality-inspections", json=_inspection(record["id"], **overrides))
    assert response.status_code == 422
    assert error_code(response) == code


@pytest.mark.parametrize(
    "overrides",
    [
        {"inspected_at": "2026-01-10T08:00:00"},  # naive timestamps are rejected
        {"inspected_quantity": 0},
        {"defect_quantity": -1},
    ],
)
def test_invalid_inspection_fields(api: TestClient, record: dict, overrides: dict) -> None:
    response = api.post(f"{API}/quality-inspections", json=_inspection(record["id"], **overrides))
    assert response.status_code == 422
    assert error_code(response) == "validation_error"


def test_future_inspection_is_rejected(api: TestClient, record: dict) -> None:
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    response = api.post(
        f"{API}/quality-inspections", json=_inspection(record["id"], inspected_at=future)
    )
    assert response.status_code == 422
    assert error_code(response) == "future_timestamp"


def test_list_inspections_with_filters(api: TestClient, record: dict) -> None:
    dim, surf = defect_category(api, "DIM"), defect_category(api, "SURF")
    post(api, "/quality-inspections", _inspection(
        record["id"], inspected_at="2026-01-10T08:00:00Z", defect_quantity=2,
        defect_category_id=dim["id"]))
    post(api, "/quality-inspections", _inspection(
        record["id"], inspected_at="2026-01-11T08:00:00Z", defect_quantity=1,
        defect_category_id=surf["id"]))
    post(api, "/quality-inspections",
         _inspection(record["id"], inspected_at="2026-01-12T08:00:00Z"))

    def query(**params: object) -> dict:
        response = api.get(f"{API}/quality-inspections", params=params)
        assert response.status_code == 200, response.text
        return response.json()

    assert query()["total"] == 3
    assert query(defect_category_id=dim["id"])["total"] == 1
    assert query(has_defects=True)["total"] == 2
    assert query(has_defects=False)["total"] == 1
    assert query(production_record_id=record["id"])["total"] == 3
    window = query(inspected_from="2026-01-11T00:00:00Z", inspected_to="2026-01-12T00:00:00Z")
    assert window["total"] == 1

    naive = api.get(f"{API}/quality-inspections", params={"inspected_from": "2026-01-11T00:00:00"})
    assert naive.status_code == 422
    reversed_range = api.get(
        f"{API}/quality-inspections",
        params={"inspected_from": "2026-01-12T00:00:00Z", "inspected_to": "2026-01-11T00:00:00Z"},
    )
    assert error_code(reversed_range) == "invalid_date_range"


def test_update_inspection_revalidates(api: TestClient, record: dict) -> None:
    created = post(api, "/quality-inspections", _inspection(record["id"]))
    url = f"{API}/quality-inspections/{created['id']}"

    missing_category = api.patch(url, json={"defect_quantity": 4})
    assert error_code(missing_category) == "defect_category_required"

    category = defect_category(api)
    updated = api.patch(url, json={"defect_quantity": 4, "defect_category_id": category["id"]})
    assert updated.status_code == 200
    assert updated.json()["defect_quantity"] == 4

    # the production reference is immutable
    assert api.patch(url, json={"production_record_id": record["id"]}).status_code == 422
    assert api.get(f"{API}/quality-inspections/999").status_code == 404


def test_production_date_is_a_plain_calendar_date(api: TestClient, record: dict) -> None:
    assert date.fromisoformat(record["production_date"]) == date(2026, 1, 10)