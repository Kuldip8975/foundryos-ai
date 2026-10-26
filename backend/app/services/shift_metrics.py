"""Deterministic shift performance metrics (Module 3).

Pure database reads; no AI involvement. These figures are the source of truth
for shift reports.

Definitions (all ratios are fractions 0–1, ``None`` when the denominator is 0):

* A *shift* is a plant calendar date (``production_date``) plus a shift code.
  Production and quality figures use exactly the production records with that
  date and code; inspections count toward the record they inspect.
* ``target_achievement`` = actual ÷ target.
* ``rejection_rate``     = rejected ÷ **actual** output (all units produced).
* ``first_pass_yield``   = accepted ÷ (accepted + rejected).
* ``defect_rate``        = defects ÷ inspected units (inspection sample).
* **Downtime** needs the shift's time window ``[window_start, window_end)``
  (UTC). Each event counts only its overlap with the window; ongoing events
  count up to ``now`` or the window end, whichever is earlier. Plant-wide
  (all machines). Without a window, downtime is reported as unavailable.
* **Maintenance**: ``raised_in_window`` counts requests created inside the
  window. ``open_now`` is the *current* backlog (open + in progress): status
  history is not stored, so the backlog as of the shift cannot be reconstructed.
* **Previous comparable shift**: the most recent earlier ``production_date``
  that has records with the same shift code (and data-source filter). Its
  downtime uses the same window moved back by the same number of days.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
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
from app.schemas.shift_reports import ShiftMetrics

TOP_N = 10
TOP_REASONS = 5
REASON_CHARS = 120
UNASSIGNED = "Unassigned"
OPEN_STATUSES = (MaintenanceStatus.OPEN.value, MaintenanceStatus.IN_PROGRESS.value)


@dataclass(frozen=True)
class ShiftScope:
    production_date: date
    shift: str
    window_start: datetime | None = None
    window_end: datetime | None = None
    data_source: DataSource | None = None

    @property
    def has_window(self) -> bool:
        return self.window_start is not None and self.window_end is not None


def ratio(numerator: int | None, denominator: int | None) -> float | None:
    """Safe division: ``None`` (not available) instead of 0 or an error."""
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def _int(value: Any) -> int:
    return int(value or 0)


def _diff(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return current - previous


# --------------------------------------------------------------------------- production + quality


def _record_filter(scope: ShiftScope, production_date: date) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [
        ProductionRecord.production_date == production_date,
        ProductionRecord.shift == scope.shift,
    ]
    if scope.data_source is not None:
        conditions.append(ProductionRecord.data_source == scope.data_source.value)
    return conditions


def _inspection_filter(scope: ShiftScope, production_date: date) -> list[ColumnElement[bool]]:
    conditions = _record_filter(scope, production_date)
    if scope.data_source is not None:
        conditions.append(QualityInspection.data_source == scope.data_source.value)
    return conditions


def _production(db: Session, scope: ShiftScope, production_date: date) -> dict[str, Any]:
    row = db.execute(
        select(
            func.count(ProductionRecord.id),
            func.sum(ProductionRecord.target_quantity),
            func.sum(ProductionRecord.actual_quantity),
            func.sum(ProductionRecord.accepted_quantity),
            func.sum(ProductionRecord.rejected_quantity),
        ).where(*_record_filter(scope, production_date))
    ).one()
    count, target, actual, accepted, rejected = (_int(v) for v in row)
    return {
        "record_count": count,
        "target_quantity": target,
        "actual_quantity": actual,
        "accepted_quantity": accepted,
        "rejected_quantity": rejected,
        "pending_quantity": actual - accepted - rejected,
        "target_achievement": ratio(actual, target),
        "rejection_rate": ratio(rejected, actual),
        "first_pass_yield": ratio(accepted, accepted + rejected),
    }


def _production_by_machine(db: Session, scope: ShiftScope) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            Machine.code,
            func.count(ProductionRecord.id),
            func.sum(ProductionRecord.target_quantity),
            func.sum(ProductionRecord.actual_quantity),
            func.sum(ProductionRecord.rejected_quantity),
        )
        .select_from(ProductionRecord)
        .outerjoin(Machine, ProductionRecord.machine_id == Machine.id)
        .where(*_record_filter(scope, scope.production_date))
        .group_by(Machine.code)
    ).all()
    result = []
    for code, count, target, actual, rejected in rows:
        target, actual, rejected = _int(target), _int(actual), _int(rejected)
        result.append(
            {
                "machine": code or UNASSIGNED,
                "record_count": _int(count),
                "target_quantity": target,
                "actual_quantity": actual,
                "rejected_quantity": rejected,
                "target_achievement": ratio(actual, target),
                "rejection_rate": ratio(rejected, actual),
            }
        )
    result.sort(key=lambda m: (-m["actual_quantity"], m["machine"]))
    return result[:TOP_N]


def _quality(db: Session, scope: ShiftScope, production_date: date) -> dict[str, Any]:
    row = db.execute(
        select(
            func.count(QualityInspection.id),
            func.sum(QualityInspection.inspected_quantity),
            func.sum(QualityInspection.defect_quantity),
        )
        .join(ProductionRecord, QualityInspection.production_record_id == ProductionRecord.id)
        .where(*_inspection_filter(scope, production_date))
    ).one()
    count, inspected, defects = (_int(v) for v in row)
    return {
        "inspection_count": count,
        "inspected_quantity": inspected,
        "defect_quantity": defects,
        "defect_rate": ratio(defects, inspected),
    }


def _defects_by_category(db: Session, scope: ShiftScope) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            DefectCategory.code,
            func.sum(QualityInspection.defect_quantity),
            func.count(QualityInspection.id),
        )
        .select_from(QualityInspection)
        .join(ProductionRecord, QualityInspection.production_record_id == ProductionRecord.id)
        .outerjoin(DefectCategory, QualityInspection.defect_category_id == DefectCategory.id)
        .where(
            QualityInspection.defect_quantity > 0,
            *_inspection_filter(scope, scope.production_date),
        )
        .group_by(DefectCategory.code)
    ).all()
    result = [
        {
            "category": code or "Uncategorised",
            "defect_quantity": _int(defects),
            "inspection_count": _int(count),
        }
        for code, defects, count in rows
    ]
    result.sort(key=lambda c: (-c["defect_quantity"], c["category"]))
    return result[:TOP_N]


# --------------------------------------------------------------------------- downtime + maintenance


def _downtime(
    db: Session, scope: ShiftScope, start: datetime | None, end: datetime | None, now: datetime
) -> dict[str, Any]:
    if start is None or end is None:
        return {
            "available": False, "event_count": None, "ongoing_count": None,
            "downtime_seconds": None, "by_machine": [], "top_reasons": [],
        }
    effective_end = min(end, now)
    conditions: list[ColumnElement[bool]] = [
        MachineDowntimeEvent.started_at < effective_end,
        or_(MachineDowntimeEvent.ended_at.is_(None), MachineDowntimeEvent.ended_at > start),
    ]
    if scope.data_source is not None:
        conditions.append(MachineDowntimeEvent.data_source == scope.data_source.value)

    events = []
    if start < effective_end:
        events = db.execute(
            select(
                Machine.code,
                MachineDowntimeEvent.started_at,
                MachineDowntimeEvent.ended_at,
                MachineDowntimeEvent.reason,
            )
            .join(Machine, MachineDowntimeEvent.machine_id == Machine.id)
            .where(*conditions)
        ).all()

    machines: dict[str, dict[str, int]] = defaultdict(
        lambda: {"event_count": 0, "ongoing_count": 0, "downtime_seconds": 0}
    )
    reasons: dict[str, dict[str, int]] = defaultdict(
        lambda: {"event_count": 0, "downtime_seconds": 0}
    )
    for code, started_at, ended_at, reason in events:
        overlap = max(
            0, int((min(ended_at or now, effective_end) - max(started_at, start)).total_seconds())
        )
        machine = machines[code]
        machine["event_count"] += 1
        machine["ongoing_count"] += 1 if ended_at is None else 0
        machine["downtime_seconds"] += overlap
        bucket = reasons[(reason or "").strip()[:REASON_CHARS] or "Unspecified"]
        bucket["event_count"] += 1
        bucket["downtime_seconds"] += overlap

    by_machine = sorted(
        ({"machine": code, **totals} for code, totals in machines.items()),
        key=lambda m: (-m["downtime_seconds"], m["machine"]),
    )
    top_reasons = sorted(
        ({"reason": reason, **totals} for reason, totals in reasons.items()),
        key=lambda r: (-r["downtime_seconds"], r["reason"]),
    )
    return {
        "available": True,
        "event_count": sum(m["event_count"] for m in by_machine),
        "ongoing_count": sum(m["ongoing_count"] for m in by_machine),
        "downtime_seconds": sum(m["downtime_seconds"] for m in by_machine),
        "by_machine": by_machine[:TOP_N],
        "top_reasons": top_reasons[:TOP_REASONS],
    }


def _maintenance(db: Session, scope: ShiftScope) -> dict[str, Any]:
    source = (
        [MaintenanceRequest.data_source == scope.data_source.value]
        if scope.data_source is not None
        else []
    )
    raised = None
    if scope.has_window:
        raised = _int(
            db.scalar(
                select(func.count(MaintenanceRequest.id)).where(
                    MaintenanceRequest.created_at >= scope.window_start,
                    MaintenanceRequest.created_at < scope.window_end,
                    *source,
                )
            )
        )
    by_priority = dict.fromkeys((p.value for p in MaintenancePriority), 0)
    for priority, count in db.execute(
        select(MaintenanceRequest.priority, func.count(MaintenanceRequest.id))
        .where(MaintenanceRequest.status.in_(OPEN_STATUSES), *source)
        .group_by(MaintenanceRequest.priority)
    ).all():
        by_priority[priority] = _int(count)
    return {
        "raised_in_window": raised,
        "open_now": sum(by_priority.values()),
        "open_now_by_priority": by_priority,
    }


def _data_sources(db: Session, scope: ShiftScope, now: datetime) -> dict[str, int]:
    counts = dict.fromkeys((s.value for s in DataSource), 0)
    queries = [
        select(ProductionRecord.data_source, func.count(ProductionRecord.id))
        .where(*_record_filter(scope, scope.production_date))
        .group_by(ProductionRecord.data_source),
        select(QualityInspection.data_source, func.count(QualityInspection.id))
        .join(ProductionRecord, QualityInspection.production_record_id == ProductionRecord.id)
        .where(*_inspection_filter(scope, scope.production_date))
        .group_by(QualityInspection.data_source),
    ]
    if scope.has_window:
        end = min(scope.window_end, now)  # type: ignore[type-var]
        conditions = [
            MachineDowntimeEvent.started_at < end,
            or_(
                MachineDowntimeEvent.ended_at.is_(None),
                MachineDowntimeEvent.ended_at > scope.window_start,
            ),
        ]
        if scope.data_source is not None:
            conditions.append(MachineDowntimeEvent.data_source == scope.data_source.value)
        queries.append(
            select(MachineDowntimeEvent.data_source, func.count(MachineDowntimeEvent.id))
            .where(*conditions)
            .group_by(MachineDowntimeEvent.data_source)
        )
    for query in queries:
        for source, count in db.execute(query).all():
            counts[source] = counts.get(source, 0) + _int(count)
    return counts


# --------------------------------------------------------------------------- previous shift


def _previous_date(db: Session, scope: ShiftScope) -> date | None:
    conditions: list[ColumnElement[bool]] = [
        ProductionRecord.shift == scope.shift,
        ProductionRecord.production_date < scope.production_date,
    ]
    if scope.data_source is not None:
        conditions.append(ProductionRecord.data_source == scope.data_source.value)
    return db.scalar(select(func.max(ProductionRecord.production_date)).where(*conditions))


# --------------------------------------------------------------------------- entry point


def compute_shift_metrics(
    db: Session, scope: ShiftScope, *, now: datetime | None = None
) -> dict[str, Any]:
    """All deterministic metrics for one shift, as a JSON-serialisable dict."""
    now = now or datetime.now(UTC)
    production = _production(db, scope, scope.production_date)
    quality = _quality(db, scope, scope.production_date)
    downtime = _downtime(db, scope, scope.window_start, scope.window_end, now)

    previous = None
    comparison = None
    previous_date = _previous_date(db, scope)
    if previous_date is not None:
        prev_production = _production(db, scope, previous_date)
        prev_quality = _quality(db, scope, previous_date)
        prev_downtime_seconds = None
        if scope.has_window:
            shift_back = timedelta(days=(scope.production_date - previous_date).days)
            prev_downtime_seconds = _downtime(
                db, scope, scope.window_start - shift_back,  # type: ignore[operator]
                scope.window_end - shift_back, now,  # type: ignore[operator]
            )["downtime_seconds"]
        previous = {
            "production_date": previous_date,
            "production": prev_production,
            "quality": prev_quality,
            "downtime_seconds": prev_downtime_seconds,
        }
        comparison = {
            "actual_quantity_change": (
                production["actual_quantity"] - prev_production["actual_quantity"]
            ),
            "target_achievement_change": _diff(
                production["target_achievement"], prev_production["target_achievement"]
            ),
            "rejection_rate_change": _diff(
                production["rejection_rate"], prev_production["rejection_rate"]
            ),
            "defect_rate_change": _diff(quality["defect_rate"], prev_quality["defect_rate"]),
            "downtime_seconds_change": (
                None
                if downtime["downtime_seconds"] is None or prev_downtime_seconds is None
                else downtime["downtime_seconds"] - prev_downtime_seconds
            ),
        }

    data_sources = _data_sources(db, scope, now)
    maintenance = _maintenance(db, scope)
    limitations = _limitations(scope, production, quality, downtime, previous, data_sources, now)

    metrics = {
        "production_date": scope.production_date,
        "shift": scope.shift,
        "window_start": scope.window_start,
        "window_end": scope.window_end,
        "data_source_filter": scope.data_source,
        "data_sources": data_sources,
        "production": production,
        "production_by_machine": _production_by_machine(db, scope),
        "quality": quality,
        "defects_by_category": _defects_by_category(db, scope),
        "downtime": downtime,
        "maintenance": maintenance,
        "previous": previous,
        "comparison": comparison,
        "limitations": limitations,
    }
    # Validate the shape once and return plain JSON types (dates as ISO strings).
    return ShiftMetrics.model_validate(metrics).model_dump(mode="json")


def _limitations(
    scope: ShiftScope,
    production: dict[str, Any],
    quality: dict[str, Any],
    downtime: dict[str, Any],
    previous: dict[str, Any] | None,
    data_sources: dict[str, int],
    now: datetime,
) -> list[str]:
    notes: list[str] = []
    if production["record_count"] == 0:
        notes.append("No production records exist for this date and shift.")
    elif production["target_quantity"] == 0:
        notes.append("Target quantity is 0, so target achievement cannot be calculated.")
    if production["pending_quantity"] > 0:
        notes.append(
            f"{production['pending_quantity']} produced units are neither accepted nor "
            "rejected yet (pending inspection)."
        )
    if quality["inspection_count"] == 0:
        notes.append("No quality inspections are recorded for this shift; defect rate unknown.")
    if not downtime["available"]:
        notes.append("No shift time window was given, so downtime was not calculated.")
    elif scope.window_end is not None and scope.window_end > now:
        notes.append("The shift window has not ended yet; downtime is counted up to now.")
    if downtime["available"] and downtime["ongoing_count"]:
        notes.append("Some downtime events are still ongoing; their duration is provisional.")
    if previous is None:
        notes.append("No earlier shift with the same code exists, so no comparison is possible.")
    notes.append(
        "Open maintenance counts are the current backlog, not the backlog at the time of "
        "the shift."
    )
    if data_sources.get(DataSource.SYNTHETIC.value):
        notes.append(
            "Includes synthetic demonstration data; it does not describe real operations."
        )
    return notes


def flatten_metrics(metrics: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flat ``{"production.actual_quantity": 1800, "downtime.by_machine.0.machine": ...}``.

    These keys are the only evidence an AI report may cite.
    """
    flat: dict[str, Any] = {}
    for key, value in metrics.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten_metrics(value, f"{path}."))
        elif isinstance(value, list):
            if not value:
                flat[path] = []
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    flat.update(flatten_metrics(item, f"{path}.{index}."))
                else:
                    flat[f"{path}.{index}"] = item
        else:
            flat[path] = value
    return flat