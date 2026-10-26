"""Dashboard analytics API and service (Module 2)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.manufacturing import (
    Machine,
    MachineDowntimeEvent,
    MaintenanceRequest,
    Product,
    ProductionRecord,
)
from app.services.analytics import DashboardFilters, dashboard_summary
from tests.helpers import (
    API,
    defect_category,
    error_code,
    machine,
    post,
    product,
    production_record,
)

URL = f"{API}/analytics/dashboard"


def summary(api: TestClient, **params: object) -> dict:
    response = api.get(URL, params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ----------------------------------------------------------------- API: empty + validation


def test_empty_database_returns_zeroes_not_errors(api: TestClient) -> None:
    body = summary(api)
    assert body["production"] == {
        "record_count": 0, "target_quantity": 0, "actual_quantity": 0,
        "accepted_quantity": 0, "rejected_quantity": 0, "pending_quantity": 0,
    }
    assert body["quality"] == {"inspection_count": 0, "inspected_quantity": 0, "defect_quantity": 0}
    assert body["trend"] == {"granularity": "day", "points": []}
    assert body["defects_by_category"] == []
    assert body["data_range"] == {"first_date": None, "last_date": None}
    assert body["shifts"] == []
    assert body["data_sources"] == {"manual": 0, "import": 0, "synthetic": 0}
    assert body["downtime"]["downtime_seconds"] == 0
    assert body["downtime"]["by_machine"] == []
    assert body["maintenance"]["open_count"] == 0
    assert set(body["maintenance"]["by_status"]) == {
        "open", "in_progress", "resolved", "closed", "cancelled",
    }
    assert body["filters"]["utc_offset_minutes"] == 0


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"date_from": "2026-01-08", "date_to": "2026-01-01"}, "invalid_date_range"),
        ({"date_from": "08/01/2026"}, "validation_error"),
        ({"utc_offset_minutes": 900}, "validation_error"),
        ({"utc_offset_minutes": -721}, "validation_error"),
        ({"shift": "night shift"}, "validation_error"),
        ({"machine_id": 0}, "validation_error"),
        ({"data_source": "spreadsheet"}, "validation_error"),
    ],
)
def test_invalid_filters_are_rejected(api: TestClient, params: dict, code: str) -> None:
    response = api.get(URL, params=params)
    assert response.status_code == 422
    assert error_code(response) == code


def test_endpoint_is_read_only(api: TestClient) -> None:
    assert api.post(URL, json={}).status_code == 405


# ----------------------------------------------------------------- API: production + quality


@pytest.fixture
def plant(api: TestClient) -> dict:
    """Two machines, two products, records on two dates and two shifts, with inspections."""
    mill, press = machine(api, "MILL"), machine(api, "PRESS")
    bracket, housing = product(api, "BRK"), product(api, "HSG")
    dim, surf = defect_category(api, "DIM"), defect_category(api, "SURF")

    records = [
        # date, shift, product, machine, target, actual, accepted, rejected
        ("2026-01-05", "A", bracket, mill, 100, 90, 80, 5),
        ("2026-01-05", "B", bracket, mill, 100, 100, 95, 5),
        ("2026-01-06", "A", housing, press, 200, 150, 140, 10),
        ("2026-01-07", "A", housing, None, 50, 50, 50, 0),
    ]
    created = []
    for day, shift, part, line, target, actual, accepted, rejected in records:
        extra = {"machine_id": line["id"]} if line else {}
        created.append(
            production_record(
                api, part["id"], production_date=day, shift=shift, target_quantity=target,
                actual_quantity=actual, accepted_quantity=accepted, rejected_quantity=rejected,
                **extra,
            )
        )
    inspections = [
        (created[0], 40, 4, dim),
        (created[1], 50, 0, None),
        (created[2], 60, 6, surf),
        (created[2], 30, 3, dim),
    ]
    for record, inspected, defects, category in inspections:
        payload = {
            "production_record_id": record["id"], "inspected_at": "2026-01-07T10:00:00Z",
            "inspected_quantity": inspected, "defect_quantity": defects,
        }
        if category:
            payload["defect_category_id"] = category["id"]
        post(api, "/quality-inspections", payload)
    return {"mill": mill, "press": press, "bracket": bracket, "housing": housing,
            "dim": dim, "surf": surf, "records": created}


def test_totals_cover_every_record(api: TestClient, plant: dict) -> None:
    body = summary(api)
    assert body["production"] == {
        "record_count": 4, "target_quantity": 450, "actual_quantity": 390,
        "accepted_quantity": 365, "rejected_quantity": 20, "pending_quantity": 5,
    }
    assert body["quality"] == {
        "inspection_count": 4, "inspected_quantity": 180, "defect_quantity": 13,
    }
    assert body["data_range"] == {"first_date": "2026-01-05", "last_date": "2026-01-07"}
    assert body["shifts"] == ["A", "B"]
    assert body["data_sources"]["manual"] == 8  # 4 records + 4 inspections
    assert body["data_sources"]["synthetic"] == 0


def test_daily_trend_sums_production_and_attributed_quality(api: TestClient, plant: dict) -> None:
    trend = summary(api)["trend"]
    assert trend["granularity"] == "day"
    assert [p["period_start"] for p in trend["points"]] == [
        "2026-01-05", "2026-01-06", "2026-01-07",
    ]
    first = trend["points"][0]
    assert first["record_count"] == 2
    assert first["actual_quantity"] == 190
    assert first["target_quantity"] == 200
    # inspections count toward the date of the record they inspect, not inspected_at
    assert first["inspected_quantity"] == 90
    assert first["defect_quantity"] == 4
    assert trend["points"][2]["inspected_quantity"] == 0


def test_defects_by_category_are_ranked(api: TestClient, plant: dict) -> None:
    categories = summary(api)["defects_by_category"]
    assert [(c["code"], c["defect_quantity"], c["inspection_count"]) for c in categories] == [
        ("DIM", 7, 2), ("SURF", 6, 1),
    ]


@pytest.mark.parametrize(
    ("filter_name", "expected_actual", "expected_defects"),
    [
        ("shift_b", 100, 0),
        ("mill", 190, 4),
        ("housing", 200, 9),
        ("single_day", 150, 9),
    ],
)
def test_filters_apply_to_production_and_quality(
    api: TestClient, plant: dict, filter_name: str, expected_actual: int, expected_defects: int
) -> None:
    params = {
        "shift_b": {"shift": "B"},
        "mill": {"machine_id": plant["mill"]["id"]},
        "housing": {"product_id": plant["housing"]["id"]},
        "single_day": {"date_from": "2026-01-06", "date_to": "2026-01-06"},
    }[filter_name]
    body = summary(api, **params)
    assert body["production"]["actual_quantity"] == expected_actual
    assert body["quality"]["defect_quantity"] == expected_defects


def test_filter_options_ignore_their_own_filter(api: TestClient, plant: dict) -> None:
    body = summary(api, shift="B", date_from="2026-01-06", date_to="2026-01-06")
    assert body["production"]["record_count"] == 0
    assert body["shifts"] == ["A", "B"]  # still selectable
    assert body["data_range"]["first_date"] == "2026-01-05"  # date range not applied here


def test_data_source_filter(api: TestClient, plant: dict) -> None:
    assert summary(api, data_source="synthetic")["production"]["record_count"] == 0
    assert summary(api, data_source="manual")["production"]["record_count"] == 4


def test_unknown_ids_give_empty_results(api: TestClient, plant: dict) -> None:
    assert summary(api, machine_id=999)["production"]["record_count"] == 0


# ------------------------------------------------------- service: buckets, downtime, maintenance


def _record(db: Session, part: Product, day: date, actual: int = 10) -> None:
    db.add(
        ProductionRecord(
            production_date=day, shift="A", product_id=part.id, target_quantity=actual,
            actual_quantity=actual, accepted_quantity=actual, rejected_quantity=0,
        )
    )


@pytest.fixture
def masters(db_session: Session) -> tuple[Machine, Machine, Product]:
    mill = Machine(code="MILL", name="Mill")
    lathe = Machine(code="LATHE", name="Lathe")
    part = Product(part_number="P-1", name="Part")
    db_session.add_all([mill, lathe, part])
    db_session.flush()
    return mill, lathe, part


NOW = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)


def test_weekly_buckets_start_on_monday(db_session: Session, masters: tuple) -> None:
    _, _, part = masters
    for day in (date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 14)):  # Wed, Thu, Wed
        _record(db_session, part, day)
    db_session.commit()
    result = dashboard_summary(
        db_session, DashboardFilters(date_from=date(2026, 1, 1), date_to=date(2026, 3, 31)), now=NOW
    )
    assert result["trend"]["granularity"] == "week"
    points = [(p["period_start"], p["actual_quantity"]) for p in result["trend"]["points"]]
    assert points == [(date(2026, 1, 5), 20), (date(2026, 1, 12), 10)]


def test_monthly_buckets_for_long_ranges(db_session: Session, masters: tuple) -> None:
    _, _, part = masters
    for day in (date(2024, 3, 3), date(2024, 3, 30), date(2026, 1, 2)):  # span > 366 days
        _record(db_session, part, day)
    db_session.commit()
    result = dashboard_summary(db_session, DashboardFilters(), now=NOW)
    assert result["trend"]["granularity"] == "month"
    points = [(p["period_start"], p["actual_quantity"]) for p in result["trend"]["points"]]
    assert points == [(date(2024, 3, 1), 20), (date(2026, 1, 1), 10)]

def _downtime(
    db: Session, line: Machine, start: datetime, end: datetime | None
) -> MachineDowntimeEvent:
    event = MachineDowntimeEvent(
        machine_id=line.id, started_at=start, ended_at=end, reason="Stop",
        status="ongoing" if end is None else "resolved",
    )
    db.add(event)
    return event


def test_downtime_is_clipped_to_the_utc_window(db_session: Session, masters: tuple) -> None:
    mill, _, _ = masters
    # 22:00 -> 02:00 UTC, spanning midnight
    _downtime(db_session, mill, datetime(2026, 1, 10, 22, tzinfo=UTC),
              datetime(2026, 1, 11, 2, tzinfo=UTC))
    db_session.commit()

    utc_day = DashboardFilters(date_from=date(2026, 1, 11), date_to=date(2026, 1, 11))
    result = dashboard_summary(db_session, utc_day, now=NOW)["downtime"]
    assert result["downtime_seconds"] == 2 * 3600
    assert result["event_count"] == 1
    assert result["window_start"] == datetime(2026, 1, 11, tzinfo=UTC)
    assert result["window_end"] == datetime(2026, 1, 12, tzinfo=UTC)

    # Plant at UTC+05:30: 11 Jan local = 10 Jan 18:30 -> 11 Jan 18:30 UTC, so all 4 hours count.
    ist_day = DashboardFilters(
        date_from=date(2026, 1, 11), date_to=date(2026, 1, 11), utc_offset_minutes=330
    )
    result = dashboard_summary(db_session, ist_day, now=NOW)["downtime"]
    assert result["downtime_seconds"] == 4 * 3600
    assert result["window_start"] == datetime(2026, 1, 10, 18, 30, tzinfo=UTC)


def test_ongoing_downtime_counts_until_now(db_session: Session, masters: tuple) -> None:
    mill, lathe, _ = masters
    _downtime(db_session, mill, datetime(2026, 2, 1, 9, tzinfo=UTC), None)
    _downtime(db_session, lathe, datetime(2026, 1, 20, 8, tzinfo=UTC),
              datetime(2026, 1, 20, 8, 30, tzinfo=UTC))
    db_session.commit()

    result = dashboard_summary(db_session, DashboardFilters(), now=NOW)["downtime"]
    assert result["ongoing_count"] == 1
    assert result["downtime_seconds"] == 3 * 3600 + 30 * 60
    assert result["window_start"] is None
    assert result["window_end"] == NOW
    assert [(m["code"], m["downtime_seconds"]) for m in result["by_machine"]] == [
        ("MILL", 3 * 3600), ("LATHE", 30 * 60),
    ]

    only_lathe = DashboardFilters(machine_id=lathe.id)
    result = dashboard_summary(db_session, only_lathe, now=NOW)["downtime"]
    assert [m["code"] for m in result["by_machine"]] == ["LATHE"]


def test_future_window_has_no_downtime(db_session: Session, masters: tuple) -> None:
    mill, _, _ = masters
    _downtime(db_session, mill, datetime(2026, 2, 1, 9, tzinfo=UTC), None)
    db_session.commit()
    future = DashboardFilters(date_from=date(2026, 3, 1), date_to=date(2026, 3, 2))
    assert dashboard_summary(db_session, future, now=NOW)["downtime"]["downtime_seconds"] == 0


def test_maintenance_backlog_and_period_counts(db_session: Session, masters: tuple) -> None:
    mill, lathe, _ = masters
    rows = [
        (mill, "open", "critical", datetime(2026, 1, 5, 8, tzinfo=UTC)),
        (mill, "in_progress", "high", datetime(2026, 1, 6, 8, tzinfo=UTC)),
        (lathe, "open", "high", datetime(2026, 1, 25, 8, tzinfo=UTC)),
        (lathe, "cancelled", "low", datetime(2026, 1, 6, 9, tzinfo=UTC)),
    ]
    for line, status, priority, created in rows:
        db_session.add(
            MaintenanceRequest(
                machine_id=line.id, issue_description="Issue", status=status,
                priority=priority, created_at=created, updated_at=created,
            )
        )
    db_session.commit()

    january_first_week = DashboardFilters(date_from=date(2026, 1, 1), date_to=date(2026, 1, 7))
    result = dashboard_summary(db_session, january_first_week, now=NOW)["maintenance"]
    assert result["open_count"] == 3  # backlog is not date-filtered
    assert result["by_status"]["cancelled"] == 1
    assert result["open_by_priority"] == {"low": 0, "medium": 0, "high": 2, "critical": 1}
    assert result["raised_in_period"] == 3

    mill_only = DashboardFilters(machine_id=mill.id)
    result = dashboard_summary(db_session, mill_only, now=NOW)["maintenance"]
    assert result["open_count"] == 2
    assert result["raised_in_period"] == 2


def test_synthetic_rows_are_counted_separately(db_session: Session, masters: tuple) -> None:
    _, _, part = masters
    db_session.add(
        ProductionRecord(
            production_date=date(2026, 1, 5), shift="A", product_id=part.id,
            target_quantity=1, actual_quantity=1, accepted_quantity=1, rejected_quantity=0,
            data_source="synthetic",
        )
    )
    _record(db_session, part, date(2026, 1, 5))
    db_session.commit()
    sources = dashboard_summary(db_session, DashboardFilters(), now=NOW)["data_sources"]
    assert sources == {"manual": 1, "import": 0, "synthetic": 1}