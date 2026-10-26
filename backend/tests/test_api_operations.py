"""Machine downtime and maintenance requests API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tests.helpers import API, error_code, machine, post

# --------------------------------------------------------------------------- downtime


def _downtime(machine_id: int, start: str, end: str | None = None, **extra: object) -> dict:
    payload: dict[str, object] = {"machine_id": machine_id, "started_at": start, "reason": "Stop"}
    if end is not None:
        payload["ended_at"] = end
    payload.update(extra)
    return payload


def test_ongoing_and_resolved_status_is_derived(api: TestClient) -> None:
    mill = machine(api)
    ongoing = post(api, "/downtime-events", _downtime(mill["id"], "2026-01-10T10:00:00Z"))
    assert ongoing["status"] == "ongoing"
    assert ongoing["duration_seconds"] is None

    other = machine(api, "M-02")
    resolved = post(
        api, "/downtime-events",
        _downtime(other["id"], "2026-01-10T08:00:00Z", "2026-01-10T09:30:00Z"),
    )
    assert resolved["status"] == "resolved"
    assert resolved["duration_seconds"] == 90 * 60


def test_status_cannot_be_set_by_client(api: TestClient) -> None:
    mill = machine(api)
    response = api.post(
        f"{API}/downtime-events",
        json=_downtime(mill["id"], "2026-01-10T08:00:00Z", status="resolved"),
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "end",
    ["2026-01-10T07:59:00Z", "2026-01-10T08:00:00Z"],  # before, and equal to, the start
)
def test_end_must_be_after_start(api: TestClient, end: str) -> None:
    mill = machine(api)
    response = api.post(
        f"{API}/downtime-events", json=_downtime(mill["id"], "2026-01-10T08:00:00Z", end)
    )
    assert response.status_code == 422
    assert error_code(response) == "invalid_date_range"


def test_future_downtime_is_rejected(api: TestClient) -> None:
    mill = machine(api)
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    response = api.post(f"{API}/downtime-events", json=_downtime(mill["id"], future))
    assert error_code(response) == "future_timestamp"


def test_overlapping_downtime_on_the_same_machine_is_rejected(api: TestClient) -> None:
    mill, lathe = machine(api, "MILL"), machine(api, "LATHE")
    post(api, "/downtime-events",
         _downtime(mill["id"], "2026-01-10T08:00:00Z", "2026-01-10T10:00:00Z"))

    overlap = api.post(
        f"{API}/downtime-events",
        json=_downtime(mill["id"], "2026-01-10T09:00:00Z", "2026-01-10T11:00:00Z"),
    )
    assert overlap.status_code == 409
    assert error_code(overlap) == "overlapping_downtime"

    # touching periods and other machines are fine
    post(api, "/downtime-events",
         _downtime(mill["id"], "2026-01-10T10:00:00Z", "2026-01-10T10:30:00Z"))
    post(api, "/downtime-events",
         _downtime(lathe["id"], "2026-01-10T09:00:00Z", "2026-01-10T11:00:00Z"))


def test_only_one_ongoing_event_per_machine(api: TestClient) -> None:
    mill = machine(api)
    post(api, "/downtime-events", _downtime(mill["id"], "2026-01-10T08:00:00Z"))
    second = api.post(f"{API}/downtime-events", json=_downtime(mill["id"], "2026-01-11T08:00:00Z"))
    assert second.status_code == 409
    assert error_code(second) == "overlapping_downtime"


def test_resolve_and_no_reopen(api: TestClient) -> None:
    mill = machine(api)
    event = post(api, "/downtime-events", _downtime(mill["id"], "2026-01-10T08:00:00Z"))
    url = f"{API}/downtime-events/{event['id']}"

    resolved = api.patch(url, json={"ended_at": "2026-01-10T08:45:00Z"})
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["duration_seconds"] == 45 * 60

    reopen = api.patch(url, json={"ended_at": None})
    assert reopen.status_code == 409
    assert error_code(reopen) == "invalid_status_transition"

    bad_start = api.patch(url, json={"started_at": "2026-01-10T09:00:00Z"})
    assert error_code(bad_start) == "invalid_date_range"


def test_list_downtime_filters(api: TestClient) -> None:
    mill, lathe = machine(api, "MILL"), machine(api, "LATHE")
    post(api, "/downtime-events",
         _downtime(mill["id"], "2026-01-10T08:00:00Z", "2026-01-10T09:00:00Z"))
    post(api, "/downtime-events", _downtime(mill["id"], "2026-01-11T08:00:00Z"))
    post(api, "/downtime-events",
         _downtime(lathe["id"], "2026-01-12T08:00:00Z", "2026-01-12T08:30:00Z"))

    def query(**params: object) -> dict:
        response = api.get(f"{API}/downtime-events", params=params)
        assert response.status_code == 200, response.text
        return response.json()

    assert query()["total"] == 3
    assert query(machine_id=mill["id"])["total"] == 2
    assert query(status="ongoing")["total"] == 1
    assert query(status="resolved", machine_id=lathe["id"])["total"] == 1
    assert query(started_from="2026-01-11T00:00:00Z")["total"] == 2
    assert api.get(f"{API}/downtime-events", params={"status": "paused"}).status_code == 422


def test_downtime_requires_existing_machine(api: TestClient) -> None:
    response = api.post(f"{API}/downtime-events", json=_downtime(999, "2026-01-10T08:00:00Z"))
    assert response.status_code == 422
    assert error_code(response) == "invalid_reference"


# --------------------------------------------------------------------------- maintenance


@pytest.fixture
def request_url(api: TestClient) -> str:
    mill = machine(api)
    created = post(api, "/maintenance-requests", {
        "machine_id": mill["id"], "issue_description": "Spindle vibration", "priority": "high",
    })
    return f"{API}/maintenance-requests/{created['id']}"


def test_new_requests_start_open(api: TestClient) -> None:
    mill = machine(api)
    created = post(api, "/maintenance-requests", {
        "machine_id": mill["id"], "issue_description": "Coolant leak",
    })
    assert created["status"] == "open"
    assert created["priority"] == "medium"
    assert created["resolved_at"] is None
    assert datetime.fromisoformat(created["created_at"]).utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "extra",
    [{"status": "resolved"}, {"priority": "urgent"}, {"issue_description": ""}],
)
def test_invalid_create_payloads(api: TestClient, extra: dict[str, object]) -> None:
    mill = machine(api)
    payload = {"machine_id": mill["id"], "issue_description": "Leak", **extra}
    response = api.post(f"{API}/maintenance-requests", json=payload)
    assert response.status_code == 422
    assert error_code(response) == "validation_error"


def test_full_lifecycle(api: TestClient, request_url: str) -> None:
    assert api.patch(request_url, json={"status": "in_progress"}).json()["status"] == "in_progress"

    resolved = api.patch(
        request_url, json={"status": "resolved", "resolution_notes": "Replaced bearing"}
    ).json()
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"] is not None

    closed = api.patch(request_url, json={"status": "closed"}).json()
    assert closed["status"] == "closed"
    assert closed["resolved_at"] == resolved["resolved_at"]
    assert closed["resolution_notes"] == "Replaced bearing"


def test_resolution_requires_notes(api: TestClient, request_url: str) -> None:
    api.patch(request_url, json={"status": "in_progress"})
    response = api.patch(request_url, json={"status": "resolved"})
    assert response.status_code == 422
    assert error_code(response) == "resolution_notes_required"


@pytest.mark.parametrize("target", ["resolved", "closed"])
def test_invalid_transitions_from_open(api: TestClient, request_url: str, target: str) -> None:
    response = api.patch(request_url, json={"status": target, "resolution_notes": "n/a"})
    assert response.status_code == 409
    assert error_code(response) == "invalid_status_transition"


def test_terminal_requests_cannot_be_modified(api: TestClient, request_url: str) -> None:
    assert api.patch(request_url, json={"status": "cancelled"}).status_code == 200
    response = api.patch(request_url, json={"priority": "low"})
    assert response.status_code == 409
    assert error_code(response) == "request_closed"


def test_reopening_a_resolved_request_clears_resolved_at(api: TestClient, request_url: str) -> None:
    api.patch(request_url, json={"status": "in_progress"})
    api.patch(request_url, json={"status": "resolved", "resolution_notes": "Tightened"})
    reopened = api.patch(request_url, json={"status": "in_progress"}).json()
    assert reopened["status"] == "in_progress"
    assert reopened["resolved_at"] is None


def test_list_maintenance_filters(api: TestClient) -> None:
    mill, press = machine(api, "MILL"), machine(api, "PRESS")
    for machine_id, priority in ((mill["id"], "high"), (mill["id"], "low"), (press["id"], "high")):
        post(api, "/maintenance-requests", {
            "machine_id": machine_id, "issue_description": "Issue", "priority": priority,
        })

    def query(**params: object) -> dict:
        response = api.get(f"{API}/maintenance-requests", params=params)
        assert response.status_code == 200, response.text
        return response.json()

    assert query()["total"] == 3
    assert query(machine_id=mill["id"])["total"] == 2
    assert query(priority="high")["total"] == 2
    assert query(status="open")["total"] == 3
    assert query(status="closed")["total"] == 0
    assert query(created_from="2000-01-01T00:00:00Z", limit=1)["items"][0]["status"] == "open"


def test_maintenance_requires_existing_machine(api: TestClient) -> None:
    response = api.post(f"{API}/maintenance-requests", json={
        "machine_id": 999, "issue_description": "Leak",
    })
    assert error_code(response) == "invalid_reference"