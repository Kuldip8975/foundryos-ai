"""Deterministic shift metrics (Module 3): calculations, boundaries, comparisons."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from app.models.enums import DataSource
from app.models.manufacturing import (
    DefectCategory,
    Machine,
    MachineDowntimeEvent,
    MaintenanceRequest,
    Product,
    ProductionRecord,
    QualityInspection,
)
from app.services.shift_metrics import ShiftScope, compute_shift_metrics, flatten_metrics, ratio

DAY = date(2026, 1, 10)
LATER = datetime(2026, 2, 1, tzinfo=UTC)
WINDOW = (datetime(2026, 1, 10, 6, tzinfo=UTC), datetime(2026, 1, 10, 14, tzinfo=UTC))


@pytest.fixture
def plant(db_session: Session) -> dict:
    mill, press = Machine(code="MILL", name="Mill"), Machine(code="PRESS", name="Press")
    part = Product(part_number="P-1", name="Part")
    dim, surf = DefectCategory(code="DIM", name="Dim"), DefectCategory(code="SURF", name="Surf")
    db_session.add_all([mill, press, part, dim, surf])
    db_session.flush()
    return {"mill": mill, "press": press, "part": part, "dim": dim, "surf": surf}


def record(
    db: Session, plant: dict, day: date, shift: str, target: int, actual: int, accepted: int,
    rejected: int, machine: Machine | None = None, source: str = "manual", notes: str | None = None,
) -> ProductionRecord:
    row = ProductionRecord(
        production_date=day, shift=shift, product_id=plant["part"].id,
        machine_id=machine.id if machine else None, target_quantity=target,
        actual_quantity=actual, accepted_quantity=accepted, rejected_quantity=rejected,
        data_source=source, notes=notes,
    )
    db.add(row)
    db.flush()
    return row


def inspect(
    db: Session, row: ProductionRecord, inspected: int, defects: int, category=None
) -> None:
    db.add(
        QualityInspection(
            production_record_id=row.id, inspected_at=datetime(2026, 1, 10, 12, tzinfo=UTC),
            inspected_quantity=inspected, defect_quantity=defects,
            defect_category_id=category.id if category else None,
        )
    )


def downtime(db: Session, machine: Machine, start: datetime, end: datetime | None,
             reason: str = "Stop") -> None:
    db.add(
        MachineDowntimeEvent(
            machine_id=machine.id, started_at=start, ended_at=end, reason=reason,
            status="ongoing" if end is None else "resolved",
        )
    )


def metrics(db: Session, now: datetime = LATER, **scope: object) -> dict:
    values: dict = {"production_date": DAY, "shift": "A", **scope}
    return compute_shift_metrics(db, ShiftScope(**values), now=now)


# --------------------------------------------------------------------------- basics


def test_ratio_is_safe() -> None:
    assert ratio(1, 4) == 0.25
    assert ratio(5, 0) is None
    assert ratio(0, 0) is None
    assert ratio(None, 5) is None


def test_empty_dataset_reports_zeroes_and_unavailable_ratios(
    db_session: Session, plant: dict
) -> None:
    result = metrics(db_session)
    assert result["production"] == {
        "record_count": 0, "target_quantity": 0, "actual_quantity": 0, "accepted_quantity": 0,
        "rejected_quantity": 0, "pending_quantity": 0, "target_achievement": None,
        "rejection_rate": None, "first_pass_yield": None,
    }
    assert result["quality"]["defect_rate"] is None
    assert result["downtime"]["available"] is False
    assert result["downtime"]["downtime_seconds"] is None
    assert result["maintenance"]["raised_in_window"] is None
    assert result["previous"] is None and result["comparison"] is None
    limitations = " ".join(result["limitations"])
    assert "No production records" in limitations
    assert "No quality inspections" in limitations
    assert "No shift time window" in limitations
    assert "No earlier shift" in limitations


def test_shift_production_and_quality(db_session: Session, plant: dict) -> None:
    mill_a = record(db_session, plant, DAY, "A", 100, 90, 80, 5, plant["mill"])
    press_a = record(db_session, plant, DAY, "A", 200, 150, 140, 10, plant["press"])
    record(db_session, plant, DAY, "A", 50, 50, 50, 0)  # no machine
    other_shift = record(db_session, plant, DAY, "B", 100, 100, 100, 0, plant["mill"])
    record(db_session, plant, date(2026, 1, 11), "A", 100, 10, 10, 0, plant["mill"])  # next day
    inspect(db_session, mill_a, 40, 4, plant["dim"])
    inspect(db_session, press_a, 60, 6, plant["surf"])
    inspect(db_session, press_a, 30, 3, plant["dim"])
    inspect(db_session, other_shift, 50, 5, plant["dim"])  # different shift: excluded
    db_session.commit()

    result = metrics(db_session)
    production = result["production"]
    assert (production["target_quantity"], production["actual_quantity"]) == (350, 290)
    assert (production["accepted_quantity"], production["rejected_quantity"]) == (270, 15)
    assert production["pending_quantity"] == 5
    assert production["target_achievement"] == pytest.approx(290 / 350)
    assert production["rejection_rate"] == pytest.approx(15 / 290)  # denominator: actual output
    assert production["first_pass_yield"] == pytest.approx(270 / 285)

    machines = [m["machine"] for m in result["production_by_machine"]]
    assert machines == ["PRESS", "MILL", "Unassigned"]
    assert result["production_by_machine"][0]["rejection_rate"] == pytest.approx(10 / 150)

    assert result["quality"] == {
        "inspection_count": 3, "inspected_quantity": 130, "defect_quantity": 13,
        "defect_rate": pytest.approx(0.1),
    }
    assert [(c["category"], c["defect_quantity"]) for c in result["defects_by_category"]] == [
        ("DIM", 7), ("SURF", 6),
    ]
    assert any("pending inspection" in note for note in result["limitations"])


def test_zero_target_gives_no_achievement(db_session: Session, plant: dict) -> None:
    record(db_session, plant, DAY, "A", 0, 0, 0, 0)
    db_session.commit()
    result = metrics(db_session)
    assert result["production"]["target_achievement"] is None
    assert result["production"]["rejection_rate"] is None
    assert any("Target quantity is 0" in note for note in result["limitations"])


# --------------------------------------------------------------------------- downtime window


def _downtime_events(db: Session, plant: dict) -> None:
    downtime(db, plant["mill"], datetime(2026, 1, 10, 5, tzinfo=UTC),
             datetime(2026, 1, 10, 7, tzinfo=UTC), "Tool change")          # 1 h inside
    downtime(db, plant["mill"], datetime(2026, 1, 10, 13, 30, tzinfo=UTC),
             datetime(2026, 1, 10, 15, tzinfo=UTC), "Sensor fault")        # 30 min inside
    downtime(db, plant["mill"], datetime(2026, 1, 10, 15, tzinfo=UTC),
             datetime(2026, 1, 10, 16, tzinfo=UTC), "Tool change")         # outside
    downtime(db, plant["press"], datetime(2026, 1, 10, 10, tzinfo=UTC), None, "Tool change")
    db.commit()


def test_downtime_is_clipped_to_the_shift_window(db_session: Session, plant: dict) -> None:
    _downtime_events(db_session, plant)
    result = metrics(db_session, window_start=WINDOW[0], window_end=WINDOW[1])["downtime"]
    assert result["available"] is True
    assert result["event_count"] == 3
    assert result["ongoing_count"] == 1
    assert result["downtime_seconds"] == 3600 + 1800 + 4 * 3600  # ongoing: 10:00 -> window end
    machines = [
        (m["machine"], m["event_count"], m["downtime_seconds"]) for m in result["by_machine"]
    ]
    assert machines == [("PRESS", 1, 4 * 3600), ("MILL", 2, 3600 + 1800)]
    assert result["top_reasons"][0] == {
        "reason": "Tool change", "event_count": 2, "downtime_seconds": 3600 + 4 * 3600,
    }


def test_ongoing_shift_counts_downtime_until_now(db_session: Session, plant: dict) -> None:
    _downtime_events(db_session, plant)
    now = datetime(2026, 1, 10, 12, tzinfo=UTC)
    result = metrics(db_session, now=now, window_start=WINDOW[0], window_end=WINDOW[1])
    # the 13:30 event has not started yet at 12:00
    assert result["downtime"]["downtime_seconds"] == 3600 + 2 * 3600
    assert any("has not ended yet" in note for note in result["limitations"])


# --------------------------------------------------------------------------- previous shift


def test_previous_comparable_shift(db_session: Session, plant: dict) -> None:
    record(db_session, plant, date(2026, 1, 8), "A", 100, 80, 75, 5, plant["mill"])
    record(db_session, plant, date(2026, 1, 9), "B", 100, 100, 100, 0, plant["mill"])  # other code
    record(db_session, plant, DAY, "A", 100, 90, 85, 5, plant["mill"])
    downtime(db_session, plant["mill"], datetime(2026, 1, 8, 8, tzinfo=UTC),
             datetime(2026, 1, 8, 9, tzinfo=UTC))
    downtime(db_session, plant["mill"], datetime(2026, 1, 10, 7, tzinfo=UTC),
             datetime(2026, 1, 10, 7, 30, tzinfo=UTC))
    db_session.commit()

    result = metrics(db_session, window_start=WINDOW[0], window_end=WINDOW[1])
    assert result["previous"]["production_date"] == "2026-01-08"
    assert result["previous"]["production"]["actual_quantity"] == 80
    assert result["previous"]["downtime_seconds"] == 3600  # same window, two days earlier
    comparison = result["comparison"]
    assert comparison["actual_quantity_change"] == 10
    assert comparison["target_achievement_change"] == pytest.approx(0.9 - 0.8)
    assert comparison["rejection_rate_change"] == pytest.approx(5 / 90 - 5 / 80)
    assert comparison["defect_rate_change"] is None  # no inspections on either shift
    assert comparison["downtime_seconds_change"] == 1800 - 3600


def test_no_window_means_no_downtime_comparison(db_session: Session, plant: dict) -> None:
    record(db_session, plant, date(2026, 1, 9), "A", 100, 80, 80, 0)
    record(db_session, plant, DAY, "A", 100, 90, 90, 0)
    db_session.commit()
    comparison = metrics(db_session)["comparison"]
    assert comparison["actual_quantity_change"] == 10
    assert comparison["downtime_seconds_change"] is None


# ----------------------------------------------------------------------- provenance + maintenance


def test_data_source_filter_and_synthetic_label(db_session: Session, plant: dict) -> None:
    record(db_session, plant, DAY, "A", 100, 90, 90, 0, source="synthetic")
    record(db_session, plant, DAY, "A", 10, 10, 10, 0)
    db_session.commit()

    everything = metrics(db_session)
    assert everything["data_sources"] == {"manual": 1, "import": 0, "synthetic": 1}
    assert any("synthetic" in note for note in everything["limitations"])

    manual = metrics(db_session, data_source=DataSource.MANUAL)
    assert manual["production"]["actual_quantity"] == 10
    assert manual["data_sources"]["synthetic"] == 0
    assert not any("synthetic" in note for note in manual["limitations"])


def test_maintenance_in_window_and_current_backlog(db_session: Session, plant: dict) -> None:
    rows = [
        ("open", "critical", datetime(2026, 1, 10, 8, tzinfo=UTC)),       # in window
        ("in_progress", "high", datetime(2026, 1, 9, 8, tzinfo=UTC)),      # before window
        ("cancelled", "low", datetime(2026, 1, 10, 9, tzinfo=UTC)),        # in window, closed
    ]
    for status, priority, created in rows:
        db_session.add(
            MaintenanceRequest(
                machine_id=plant["mill"].id, issue_description="Issue", status=status,
                priority=priority, created_at=created, updated_at=created,
            )
        )
    db_session.commit()
    result = metrics(db_session, window_start=WINDOW[0], window_end=WINDOW[1])["maintenance"]
    assert result["raised_in_window"] == 2
    assert result["open_now"] == 2
    assert result["open_now_by_priority"] == {"low": 0, "medium": 0, "high": 1, "critical": 1}


def test_flattened_keys_are_stable(db_session: Session, plant: dict) -> None:
    record(db_session, plant, DAY, "A", 100, 90, 90, 0, plant["mill"])
    db_session.commit()
    flat = flatten_metrics(metrics(db_session))
    assert flat["production.actual_quantity"] == 90
    assert flat["production_by_machine.0.machine"] == "MILL"
    assert flat["quality.defect_rate"] is None
    assert flat["defects_by_category"] == []
    assert "previous" in flat and flat["previous"] is None