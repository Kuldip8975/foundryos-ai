"""Database-level guarantees of the Module 1 schema (constraints, UTC, relationships).

These insert through the ORM directly, bypassing the service layer, to prove
the database itself rejects invalid rows (defence in depth).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError, StatementError
from sqlalchemy.orm import Session

from app.models.manufacturing import (
    DefectCategory,
    Machine,
    MachineDowntimeEvent,
    MaintenanceRequest,
    Product,
    ProductionRecord,
    QualityInspection,
)

IST = timezone(timedelta(hours=5, minutes=30))


def _master(db: Session) -> tuple[Machine, Product, DefectCategory]:
    machine = Machine(code="M-01", name="Machine 1")
    product = Product(part_number="P-1", name="Part 1")
    category = DefectCategory(code="DIM", name="Dimensional")
    db.add_all([machine, product, category])
    db.flush()
    return machine, product, category


def _record(
    product: Product, machine: Machine | None = None, **overrides: object
) -> ProductionRecord:
    values: dict[str, object] = {
        "production_date": date(2026, 1, 10),
        "shift": "A",
        "product_id": product.id,
        "machine_id": machine.id if machine else None,
        "target_quantity": 100,
        "actual_quantity": 90,
        "accepted_quantity": 85,
        "rejected_quantity": 5,
    }
    values.update(overrides)
    return ProductionRecord(**values)


def test_defaults_and_utc_audit_timestamps(db_session: Session) -> None:
    machine, _, _ = _master(db_session)
    db_session.commit()
    db_session.refresh(machine)
    assert machine.data_source == "manual"
    assert machine.is_active is True
    assert machine.created_at.tzinfo is not None
    assert machine.created_at.utcoffset() == timedelta(0)


def test_timestamps_are_normalised_to_utc(db_session: Session) -> None:
    machine, _, _ = _master(db_session)
    local_start = datetime(2026, 1, 10, 13, 30, tzinfo=IST)  # 08:00 UTC
    event = MachineDowntimeEvent(
        machine_id=machine.id, started_at=local_start, reason="Tool change", status="ongoing"
    )
    db_session.add(event)
    db_session.commit()
    db_session.expire_all()

    stored = db_session.get(MachineDowntimeEvent, event.id)
    assert stored is not None
    assert stored.started_at == datetime(2026, 1, 10, 8, 0, tzinfo=UTC)
    assert stored.started_at.utcoffset() == timedelta(0)


def test_naive_timestamps_are_rejected(db_session: Session) -> None:
    machine, _, _ = _master(db_session)
    db_session.add(
        MachineDowntimeEvent(
            machine_id=machine.id, started_at=datetime(2026, 1, 10, 8, 0),
            reason="Tool change", status="ongoing",
        )
    )
    with pytest.raises(StatementError, match="Naive datetime"):
        db_session.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        {"accepted_quantity": 90, "rejected_quantity": 5},  # 95 > actual 90
        {"actual_quantity": -1, "accepted_quantity": 0, "rejected_quantity": 0},
        {"target_quantity": -5},
    ],
)
def test_database_rejects_invalid_production_quantities(
    db_session: Session, overrides: dict[str, int]
) -> None:
    machine, product, _ = _master(db_session)
    db_session.add(_record(product, machine, **overrides))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_database_enforces_foreign_keys(db_session: Session) -> None:
    db_session.add(
        ProductionRecord(
            production_date=date(2026, 1, 10), shift="A", product_id=999,
            target_quantity=1, actual_quantity=1, accepted_quantity=1, rejected_quantity=0,
        )
    )
    # PostgreSQL raises IntegrityError; SQLite reports a failed foreign key on an
    # INSERT ... RETURNING as OperationalError. Either way the row must be rejected.
    with pytest.raises((IntegrityError, OperationalError), match="(?i)foreign key"):
        db_session.flush()


def test_database_requires_category_for_defects(db_session: Session) -> None:
    machine, product, _ = _master(db_session)
    record = _record(product, machine)
    db_session.add(record)
    db_session.flush()
    db_session.add(
        QualityInspection(
            production_record_id=record.id, inspected_at=datetime(2026, 1, 10, tzinfo=UTC),
            inspected_quantity=10, defect_quantity=2, defect_category_id=None,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_database_keeps_downtime_status_consistent_with_end(db_session: Session) -> None:
    machine, _, _ = _master(db_session)
    db_session.add(
        MachineDowntimeEvent(
            machine_id=machine.id, started_at=datetime(2026, 1, 10, tzinfo=UTC),
            ended_at=None, reason="Stop", status="resolved",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_database_rejects_downtime_ending_before_start(db_session: Session) -> None:
    machine, _, _ = _master(db_session)
    start = datetime(2026, 1, 10, 8, 0, tzinfo=UTC)
    db_session.add(
        MachineDowntimeEvent(
            machine_id=machine.id, started_at=start, ended_at=start - timedelta(minutes=1),
            reason="Stop", status="resolved",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_database_requires_resolution_details_for_resolved_requests(db_session: Session) -> None:
    machine, _, _ = _master(db_session)
    db_session.add(
        MaintenanceRequest(
            machine_id=machine.id, issue_description="Leak", priority="high",
            status="resolved", resolution_notes=None, resolved_at=None,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("field", "value"),
    [("data_source", "spreadsheet"), ("priority", "urgent"), ("status", "done")],
)
def test_database_rejects_unknown_enum_values(db_session: Session, field: str, value: str) -> None:
    machine, _, _ = _master(db_session)
    values = {
        "machine_id": machine.id, "issue_description": "Leak", "priority": "high", "status": "open",
    }
    values[field] = value
    db_session.add(MaintenanceRequest(**values))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_business_keys_are_unique(db_session: Session) -> None:
    _master(db_session)
    db_session.add(Machine(code="M-01", name="Duplicate"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_relationships_navigate_both_ways(db_session: Session) -> None:
    machine, product, category = _master(db_session)
    record = _record(product, machine)
    db_session.add(record)
    db_session.flush()
    inspection = QualityInspection(
        production_record_id=record.id, inspected_at=datetime(2026, 1, 10, tzinfo=UTC),
        inspected_quantity=20, defect_quantity=1, defect_category_id=category.id,
    )
    downtime = MachineDowntimeEvent(
        machine_id=machine.id, started_at=datetime(2026, 1, 10, tzinfo=UTC),
        reason="Stop", status="ongoing",
    )
    request = MaintenanceRequest(
        machine_id=machine.id, issue_description="Leak", priority="low", status="open"
    )
    db_session.add_all([inspection, downtime, request])
    db_session.commit()
    db_session.expire_all()

    assert db_session.get(ProductionRecord, record.id).inspections[0].id == inspection.id
    assert db_session.get(QualityInspection, inspection.id).production_record.product.id == (
        product.id
    )
    assert db_session.get(DefectCategory, category.id).inspections[0].id == inspection.id
    reloaded = db_session.get(Machine, machine.id)
    assert [r.id for r in reloaded.production_records] == [record.id]
    assert [d.id for d in reloaded.downtime_events] == [downtime.id]
    assert [m.id for m in reloaded.maintenance_requests] == [request.id]