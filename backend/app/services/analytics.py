"""Read-only aggregates for the manufacturing dashboard (Module 2).

All figures are computed in the database (SUM/COUNT) from the Module 1 tables,
so totals are exact regardless of how many rows exist. Nothing is written.

Scope rules:
* **Production and quality** use the plant calendar date ``production_date``
  (``date_from``/``date_to`` inclusive) plus the shift, machine and product
  filters. Inspections are attributed to the date of the production record they
  inspect, so quality and production figures always describe the same output.
* **Downtime** is machine-level: the machine filter applies, shift and product
  do not. The date range becomes a UTC window
  ``[date_from 00:00, date_to + 1 day 00:00)`` in the plant's UTC offset, and
  each event contributes only its overlap with that window. Ongoing events
  count up to ``now`` (or the window end, if earlier).
* **Maintenance** status counts are the current backlog (not date-filtered);
  ``raised_in_period`` counts requests created inside the window.
* ``data_source`` (manual / import / synthetic) applies to every section.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.enums import DataSource, MaintenancePriority, MaintenanceStatus
from app.models.manufacturing import (
    DefectCategory,
    Machine,
    MachineDowntimeEvent,
    MaintenanceRequest,
    ProductionRecord,
    QualityInspection,
)
from app.services.common import validate_range

# Trend bucket size is chosen from the length of the period shown.
DAILY_MAX_DAYS = 62
WEEKLY_MAX_DAYS = 366

OPEN_MAINTENANCE_STATUSES = (MaintenanceStatus.OPEN.value, MaintenanceStatus.IN_PROGRESS.value)
UNCATEGORISED = "Uncategorised"


@dataclass(frozen=True)
class DashboardFilters:
    date_from: date | None = None
    date_to: date | None = None
    shift: str | None = None
    machine_id: int | None = None
    product_id: int | None = None
    data_source: DataSource | None = None
    utc_offset_minutes: int = 0


# --------------------------------------------------------------------------- helpers


def _record_conditions(
    f: DashboardFilters, *, dates: bool = True, shift: bool = True
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if dates and f.date_from is not None:
        conditions.append(ProductionRecord.production_date >= f.date_from)
    if dates and f.date_to is not None:
        conditions.append(ProductionRecord.production_date <= f.date_to)
    if shift and f.shift is not None:
        conditions.append(ProductionRecord.shift == f.shift)
    if f.machine_id is not None:
        conditions.append(ProductionRecord.machine_id == f.machine_id)
    if f.product_id is not None:
        conditions.append(ProductionRecord.product_id == f.product_id)
    if f.data_source is not None:
        conditions.append(ProductionRecord.data_source == f.data_source.value)
    return conditions


def _inspection_conditions(f: DashboardFilters) -> list[ColumnElement[bool]]:
    conditions = _record_conditions(f)
    if f.data_source is not None:
        conditions.append(QualityInspection.data_source == f.data_source.value)
    return conditions


def _int(value: Any) -> int:
    return int(value or 0)


def _window(
    f: DashboardFilters, now: datetime
) -> tuple[datetime | None, datetime, datetime | None]:
    """(window start, effective end capped at now, nominal end) as UTC datetimes."""
    plant_tz = timezone(timedelta(minutes=f.utc_offset_minutes))
    start = None
    if f.date_from is not None:
        start = datetime.combine(f.date_from, time.min, tzinfo=plant_tz).astimezone(UTC)
    nominal_end = None
    if f.date_to is not None:
        next_day = f.date_to + timedelta(days=1)
        nominal_end = datetime.combine(next_day, time.min, tzinfo=plant_tz).astimezone(UTC)
    end = now if nominal_end is None else min(nominal_end, now)
    return start, end, nominal_end


def _bucket(day: date, granularity: str) -> date:
    if granularity == "week":
        return day - timedelta(days=day.weekday())  # ISO week, Monday start
    if granularity == "month":
        return day.replace(day=1)
    return day


def _granularity(first: date | None, last: date | None) -> str:
    if first is None or last is None:
        return "day"
    span_days = (last - first).days + 1
    if span_days <= DAILY_MAX_DAYS:
        return "day"
    if span_days <= WEEKLY_MAX_DAYS:
        return "week"
    return "month"


# --------------------------------------------------------------------------- sections


def _production_totals(db: Session, f: DashboardFilters) -> dict[str, int]:
    row = db.execute(
        select(
            func.count(ProductionRecord.id),
            func.sum(ProductionRecord.target_quantity),
            func.sum(ProductionRecord.actual_quantity),
            func.sum(ProductionRecord.accepted_quantity),
            func.sum(ProductionRecord.rejected_quantity),
        ).where(*_record_conditions(f))
    ).one()
    count, target, actual, accepted, rejected = (_int(v) for v in row)
    return {
        "record_count": count,
        "target_quantity": target,
        "actual_quantity": actual,
        "accepted_quantity": accepted,
        "rejected_quantity": rejected,
        "pending_quantity": actual - accepted - rejected,
    }


def _quality_totals(db: Session, f: DashboardFilters) -> dict[str, int]:
    row = db.execute(
        select(
            func.count(QualityInspection.id),
            func.sum(QualityInspection.inspected_quantity),
            func.sum(QualityInspection.defect_quantity),
        )
        .join(ProductionRecord, QualityInspection.production_record_id == ProductionRecord.id)
        .where(*_inspection_conditions(f))
    ).one()
    count, inspected, defects = (_int(v) for v in row)
    return {"inspection_count": count, "inspected_quantity": inspected, "defect_quantity": defects}


def _trend(db: Session, f: DashboardFilters) -> dict[str, Any]:
    production_rows = db.execute(
        select(
            ProductionRecord.production_date,
            func.count(ProductionRecord.id),
            func.sum(ProductionRecord.target_quantity),
            func.sum(ProductionRecord.actual_quantity),
            func.sum(ProductionRecord.accepted_quantity),
            func.sum(ProductionRecord.rejected_quantity),
        )
        .where(*_record_conditions(f))
        .group_by(ProductionRecord.production_date)
    ).all()
    quality_rows = db.execute(
        select(
            ProductionRecord.production_date,
            func.sum(QualityInspection.inspected_quantity),
            func.sum(QualityInspection.defect_quantity),
        )
        .join(ProductionRecord, QualityInspection.production_record_id == ProductionRecord.id)
        .where(*_inspection_conditions(f))
        .group_by(ProductionRecord.production_date)
    ).all()

    days = [row[0] for row in production_rows]
    granularity = _granularity(
        f.date_from or (min(days) if days else None), f.date_to or (max(days) if days else None)
    )
    keys = (
        "record_count", "target_quantity", "actual_quantity", "accepted_quantity",
        "rejected_quantity", "inspected_quantity", "defect_quantity",
    )
    buckets: dict[date, dict[str, int]] = defaultdict(lambda: dict.fromkeys(keys, 0))
    for day, count, target, actual, accepted, rejected in production_rows:
        bucket = buckets[_bucket(day, granularity)]
        bucket["record_count"] += _int(count)
        bucket["target_quantity"] += _int(target)
        bucket["actual_quantity"] += _int(actual)
        bucket["accepted_quantity"] += _int(accepted)
        bucket["rejected_quantity"] += _int(rejected)
    for day, inspected, defects in quality_rows:
        bucket = buckets[_bucket(day, granularity)]
        bucket["inspected_quantity"] += _int(inspected)
        bucket["defect_quantity"] += _int(defects)

    points = [{"period_start": start, **values} for start, values in sorted(buckets.items())]
    return {"granularity": granularity, "points": points}


def _defects_by_category(db: Session, f: DashboardFilters) -> list[dict[str, Any]]:
    defect_sum = func.sum(QualityInspection.defect_quantity)
    rows = db.execute(
        select(
            DefectCategory.id,
            DefectCategory.code,
            DefectCategory.name,
            defect_sum,
            func.count(QualityInspection.id),
        )
        .select_from(QualityInspection)
        .join(ProductionRecord, QualityInspection.production_record_id == ProductionRecord.id)
        .outerjoin(DefectCategory, QualityInspection.defect_category_id == DefectCategory.id)
        .where(QualityInspection.defect_quantity > 0, *_inspection_conditions(f))
        .group_by(DefectCategory.id, DefectCategory.code, DefectCategory.name)
    ).all()
    result = [
        {
            "defect_category_id": category_id,
            "code": code,
            "name": name or UNCATEGORISED,
            "defect_quantity": _int(defects),
            "inspection_count": _int(count),
        }
        for category_id, code, name, defects, count in rows
    ]
    result.sort(key=lambda item: (-item["defect_quantity"], item["code"] or ""))
    return result


def _downtime(db: Session, f: DashboardFilters, now: datetime) -> dict[str, Any]:
    start, end, _nominal_end = _window(f, now)
    summary: dict[str, Any] = {
        "window_start": start,
        "window_end": end,
        "event_count": 0,
        "ongoing_count": 0,
        "downtime_seconds": 0,
        "by_machine": [],
    }
    if start is not None and start >= end:
        return summary  # the window lies entirely in the future

    conditions: list[ColumnElement[bool]] = [MachineDowntimeEvent.started_at < end]
    if start is not None:
        conditions.append(
            or_(MachineDowntimeEvent.ended_at.is_(None), MachineDowntimeEvent.ended_at > start)
        )
    if f.machine_id is not None:
        conditions.append(MachineDowntimeEvent.machine_id == f.machine_id)
    if f.data_source is not None:
        conditions.append(MachineDowntimeEvent.data_source == f.data_source.value)

    events = db.execute(
        select(
            MachineDowntimeEvent.machine_id,
            MachineDowntimeEvent.started_at,
            MachineDowntimeEvent.ended_at,
        ).where(and_(*conditions))
    ).all()

    per_machine: dict[int, dict[str, int]] = defaultdict(
        lambda: {"event_count": 0, "ongoing_count": 0, "downtime_seconds": 0}
    )
    for machine_id, started_at, ended_at in events:
        overlap_start = started_at if start is None else max(started_at, start)
        overlap_end = min(ended_at or now, end)
        seconds = max(0, int((overlap_end - overlap_start).total_seconds()))
        totals = per_machine[machine_id]
        totals["event_count"] += 1
        totals["ongoing_count"] += 1 if ended_at is None else 0
        totals["downtime_seconds"] += seconds

    if per_machine:
        machines = {
            machine_id: (code, name)
            for machine_id, code, name in db.execute(
                select(Machine.id, Machine.code, Machine.name).where(
                    Machine.id.in_(list(per_machine))
                )
            ).all()
        }
        by_machine = [
            {
                "machine_id": machine_id,
                "code": machines[machine_id][0],
                "name": machines[machine_id][1],
                **totals,
            }
            for machine_id, totals in per_machine.items()
        ]
        by_machine.sort(key=lambda item: (-item["downtime_seconds"], item["code"]))
        summary["by_machine"] = by_machine
        summary["event_count"] = sum(item["event_count"] for item in by_machine)
        summary["ongoing_count"] = sum(item["ongoing_count"] for item in by_machine)
        summary["downtime_seconds"] = sum(item["downtime_seconds"] for item in by_machine)
    return summary


def _maintenance_conditions(f: DashboardFilters) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if f.machine_id is not None:
        conditions.append(MaintenanceRequest.machine_id == f.machine_id)
    if f.data_source is not None:
        conditions.append(MaintenanceRequest.data_source == f.data_source.value)
    return conditions


def _maintenance(db: Session, f: DashboardFilters, now: datetime) -> dict[str, Any]:
    conditions = _maintenance_conditions(f)
    by_status = dict.fromkeys((s.value for s in MaintenanceStatus), 0)
    for status_value, count in db.execute(
        select(MaintenanceRequest.status, func.count(MaintenanceRequest.id))
        .where(*conditions)
        .group_by(MaintenanceRequest.status)
    ).all():
        by_status[status_value] = _int(count)

    open_by_priority = dict.fromkeys((p.value for p in MaintenancePriority), 0)
    for priority, count in db.execute(
        select(MaintenanceRequest.priority, func.count(MaintenanceRequest.id))
        .where(MaintenanceRequest.status.in_(OPEN_MAINTENANCE_STATUSES), *conditions)
        .group_by(MaintenanceRequest.priority)
    ).all():
        open_by_priority[priority] = _int(count)

    start, _end, nominal_end = _window(f, now)
    period = list(conditions)
    if start is not None:
        period.append(MaintenanceRequest.created_at >= start)
    if nominal_end is not None:
        period.append(MaintenanceRequest.created_at < nominal_end)
    raised = db.scalar(select(func.count(MaintenanceRequest.id)).where(*period))

    return {
        "by_status": by_status,
        "open_by_priority": open_by_priority,
        "open_count": sum(by_status[s] for s in OPEN_MAINTENANCE_STATUSES),
        "raised_in_period": _int(raised),
    }


def _data_sources(db: Session, f: DashboardFilters, now: datetime) -> dict[str, int]:
    """Rows in scope per provenance, so the UI can label synthetic data."""
    counts = dict.fromkeys((s.value for s in DataSource), 0)

    def add(rows: list[Any]) -> None:
        for source, count in rows:
            counts[source] = counts.get(source, 0) + _int(count)

    add(
        db.execute(
            select(ProductionRecord.data_source, func.count(ProductionRecord.id))
            .where(*_record_conditions(f))
            .group_by(ProductionRecord.data_source)
        ).all()
    )
    add(
        db.execute(
            select(QualityInspection.data_source, func.count(QualityInspection.id))
            .join(ProductionRecord, QualityInspection.production_record_id == ProductionRecord.id)
            .where(*_inspection_conditions(f))
            .group_by(QualityInspection.data_source)
        ).all()
    )
    start, end, _nominal_end = _window(f, now)
    downtime = [MachineDowntimeEvent.started_at < end]
    if start is not None:
        downtime.append(
            or_(MachineDowntimeEvent.ended_at.is_(None), MachineDowntimeEvent.ended_at > start)
        )
    if f.machine_id is not None:
        downtime.append(MachineDowntimeEvent.machine_id == f.machine_id)
    if f.data_source is not None:
        downtime.append(MachineDowntimeEvent.data_source == f.data_source.value)
    add(
        db.execute(
            select(MachineDowntimeEvent.data_source, func.count(MachineDowntimeEvent.id))
            .where(*downtime)
            .group_by(MachineDowntimeEvent.data_source)
        ).all()
    )
    add(
        db.execute(
            select(MaintenanceRequest.data_source, func.count(MaintenanceRequest.id))
            .where(*_maintenance_conditions(f))
            .group_by(MaintenanceRequest.data_source)
        ).all()
    )
    return counts


# --------------------------------------------------------------------------- entry point


def dashboard_summary(
    db: Session, filters: DashboardFilters, *, now: datetime | None = None
) -> dict[str, Any]:
    """All dashboard figures for one filter set, computed in a single session."""
    validate_range(filters.date_from, filters.date_to, start_field="date_from", end_field="date_to")
    now = now or datetime.now(UTC)

    first_date, last_date = db.execute(
        select(
            func.min(ProductionRecord.production_date), func.max(ProductionRecord.production_date)
        ).where(*_record_conditions(filters, dates=False))
    ).one()
    shifts = list(
        db.scalars(
            select(ProductionRecord.shift)
            .where(*_record_conditions(filters, dates=False, shift=False))
            .distinct()
            .order_by(ProductionRecord.shift)
        )
    )

    return {
        "generated_at": now,
        "filters": {
            "date_from": filters.date_from,
            "date_to": filters.date_to,
            "shift": filters.shift,
            "machine_id": filters.machine_id,
            "product_id": filters.product_id,
            "data_source": filters.data_source,
            "utc_offset_minutes": filters.utc_offset_minutes,
        },
        "data_range": {"first_date": first_date, "last_date": last_date},
        "shifts": shifts,
        "data_sources": _data_sources(db, filters, now),
        "production": _production_totals(db, filters),
        "quality": _quality_totals(db, filters),
        "trend": _trend(db, filters),
        "defects_by_category": _defects_by_category(db, filters),
        "downtime": _downtime(db, filters, now),
        "maintenance": _maintenance(db, filters, now),
    }