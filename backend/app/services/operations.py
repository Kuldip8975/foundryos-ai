"""Machine downtime events and maintenance requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError
from app.db.types import utcnow
from app.models.enums import (
    MAINTENANCE_RESOLVED_STATUSES,
    MAINTENANCE_TRANSITIONS,
    DataSource,
    DowntimeStatus,
    MaintenancePriority,
    MaintenanceStatus,
)
from app.models.manufacturing import Machine, MachineDowntimeEvent, MaintenanceRequest
from app.services.common import (
    apply_changes,
    commit,
    ensure_not_future,
    get_or_404,
    paginate,
    require_reference,
    validate_range,
)

# --------------------------------------------------------------------------- downtime


def _downtime_status(ended_at: datetime | None) -> str:
    return (DowntimeStatus.RESOLVED if ended_at is not None else DowntimeStatus.ONGOING).value


def _validate_downtime_period(started_at: datetime, ended_at: datetime | None) -> None:
    ensure_not_future(started_at, field="started_at")
    if ended_at is not None:
        ensure_not_future(ended_at, field="ended_at")
        validate_range(
            started_at, ended_at, start_field="started_at", end_field="ended_at", allow_equal=False
        )


def _ensure_no_overlap(
    db: Session,
    *,
    machine_id: int,
    started_at: datetime,
    ended_at: datetime | None,
    exclude_id: int | None = None,
) -> None:
    """A machine cannot be in two downtime periods at once (ongoing = open-ended)."""
    stmt = select(MachineDowntimeEvent.id).where(
        MachineDowntimeEvent.machine_id == machine_id,
        or_(MachineDowntimeEvent.ended_at.is_(None), MachineDowntimeEvent.ended_at > started_at),
    )
    if ended_at is not None:
        stmt = stmt.where(MachineDowntimeEvent.started_at < ended_at)
    if exclude_id is not None:
        stmt = stmt.where(MachineDowntimeEvent.id != exclude_id)
    clash = db.scalar(stmt.limit(1))
    if clash is not None:
        raise ConflictError(
            f"This period overlaps downtime event {clash} for the same machine",
            code="overlapping_downtime",
        )


def create_downtime_event(db: Session, data: dict[str, Any]) -> MachineDowntimeEvent:
    _validate_downtime_period(data["started_at"], data.get("ended_at"))
    require_reference(db, Machine, data["machine_id"], field="machine_id", label="Machine")
    _ensure_no_overlap(
        db, machine_id=data["machine_id"], started_at=data["started_at"],
        ended_at=data.get("ended_at"),
    )
    event = MachineDowntimeEvent(
        **data, status=_downtime_status(data.get("ended_at")), data_source=DataSource.MANUAL.value
    )
    db.add(event)
    commit(db, conflict_message="A downtime event with this external_ref already exists")
    db.refresh(event)
    return event


def get_downtime_event(db: Session, event_id: int) -> MachineDowntimeEvent:
    return get_or_404(db, MachineDowntimeEvent, event_id, "Downtime event")


@dataclass(frozen=True)
class DowntimeFilters:
    started_from: datetime | None = None
    started_to: datetime | None = None
    machine_id: int | None = None
    status: DowntimeStatus | None = None
    data_source: DataSource | None = None
    # Data scope: only these machines (None = every machine).
    machine_ids: frozenset[int] | None = None


def list_downtime_events(
    db: Session, filters: DowntimeFilters, *, limit: int, offset: int
) -> tuple[list[MachineDowntimeEvent], int]:
    validate_range(
        filters.started_from, filters.started_to,
        start_field="started_from", end_field="started_to",
    )
    stmt = select(MachineDowntimeEvent)
    if filters.started_from is not None:
        stmt = stmt.where(MachineDowntimeEvent.started_at >= filters.started_from)
    if filters.started_to is not None:
        stmt = stmt.where(MachineDowntimeEvent.started_at <= filters.started_to)
    if filters.machine_id is not None:
        stmt = stmt.where(MachineDowntimeEvent.machine_id == filters.machine_id)
    if filters.machine_ids is not None:
        stmt = stmt.where(MachineDowntimeEvent.machine_id.in_(sorted(filters.machine_ids)))
    if filters.status is not None:
        stmt = stmt.where(MachineDowntimeEvent.status == filters.status.value)
    if filters.data_source is not None:
        stmt = stmt.where(MachineDowntimeEvent.data_source == filters.data_source.value)
    order = (MachineDowntimeEvent.started_at.desc(), MachineDowntimeEvent.id.desc())
    return paginate(db, stmt, order_by=order, limit=limit, offset=offset)


def update_downtime_event(
    db: Session, event_id: int, changes: dict[str, Any]
) -> MachineDowntimeEvent:
    event = get_downtime_event(db, event_id)
    if not changes:
        return event
    if "ended_at" in changes and changes["ended_at"] is None and event.ended_at is not None:
        raise ConflictError(
            "A resolved downtime event cannot be reopened; record a new event instead",
            code="invalid_status_transition",
        )
    started_at = changes.get("started_at", event.started_at)
    ended_at = changes.get("ended_at", event.ended_at)
    if "started_at" in changes or "ended_at" in changes:
        _validate_downtime_period(started_at, ended_at)
        _ensure_no_overlap(
            db, machine_id=event.machine_id, started_at=started_at, ended_at=ended_at,
            exclude_id=event.id,
        )
    apply_changes(event, changes)
    event.status = _downtime_status(ended_at)
    commit(db, conflict_message="The downtime event could not be updated")
    db.refresh(event)
    return event


# --------------------------------------------------------------------------- maintenance


def create_maintenance_request(db: Session, data: dict[str, Any]) -> MaintenanceRequest:
    require_reference(db, Machine, data["machine_id"], field="machine_id", label="Machine")
    request = MaintenanceRequest(
        **data, status=MaintenanceStatus.OPEN.value, data_source=DataSource.MANUAL.value
    )
    db.add(request)
    commit(db, conflict_message="A maintenance request with this external_ref already exists")
    db.refresh(request)
    return request


def get_maintenance_request(db: Session, request_id: int) -> MaintenanceRequest:
    return get_or_404(db, MaintenanceRequest, request_id, "Maintenance request")


@dataclass(frozen=True)
class MaintenanceFilters:
    created_from: datetime | None = None
    created_to: datetime | None = None
    machine_id: int | None = None
    status: MaintenanceStatus | None = None
    priority: MaintenancePriority | None = None
    data_source: DataSource | None = None
    # Data scope: only these machines (None = every machine).
    machine_ids: frozenset[int] | None = None


def list_maintenance_requests(
    db: Session, filters: MaintenanceFilters, *, limit: int, offset: int
) -> tuple[list[MaintenanceRequest], int]:
    validate_range(
        filters.created_from, filters.created_to,
        start_field="created_from", end_field="created_to",
    )
    stmt = select(MaintenanceRequest)
    if filters.created_from is not None:
        stmt = stmt.where(MaintenanceRequest.created_at >= filters.created_from)
    if filters.created_to is not None:
        stmt = stmt.where(MaintenanceRequest.created_at <= filters.created_to)
    if filters.machine_id is not None:
        stmt = stmt.where(MaintenanceRequest.machine_id == filters.machine_id)
    if filters.machine_ids is not None:
        stmt = stmt.where(MaintenanceRequest.machine_id.in_(sorted(filters.machine_ids)))
    if filters.status is not None:
        stmt = stmt.where(MaintenanceRequest.status == filters.status.value)
    if filters.priority is not None:
        stmt = stmt.where(MaintenanceRequest.priority == filters.priority.value)
    if filters.data_source is not None:
        stmt = stmt.where(MaintenanceRequest.data_source == filters.data_source.value)
    order = (MaintenanceRequest.created_at.desc(), MaintenanceRequest.id.desc())
    return paginate(db, stmt, order_by=order, limit=limit, offset=offset)


def update_maintenance_request(
    db: Session, request_id: int, changes: dict[str, Any]
) -> MaintenanceRequest:
    request = get_maintenance_request(db, request_id)
    if not changes:
        return request

    current = MaintenanceStatus(request.status)
    if not MAINTENANCE_TRANSITIONS[current]:
        raise ConflictError(
            f"A {current.value} maintenance request cannot be modified",
            code="request_closed",
        )

    target = MaintenanceStatus(changes.get("status", current.value))
    if target != current and target not in MAINTENANCE_TRANSITIONS[current]:
        allowed = ", ".join(sorted(s.value for s in MAINTENANCE_TRANSITIONS[current]))
        raise ConflictError(
            f"Cannot change status from {current.value} to {target.value} "
            f"(allowed: {allowed})",
            code="invalid_status_transition",
        )

    notes = changes.get("resolution_notes", request.resolution_notes)
    if target in MAINTENANCE_RESOLVED_STATUSES and not notes:
        raise BusinessRuleError(
            "resolution_notes are required to resolve a maintenance request",
            code="resolution_notes_required",
            details=[{"field": "resolution_notes"}],
        )

    apply_changes(request, changes)
    if target == MaintenanceStatus.RESOLVED and current != MaintenanceStatus.RESOLVED:
        request.resolved_at = utcnow()
    elif target not in MAINTENANCE_RESOLVED_STATUSES:
        request.resolved_at = None
    commit(db, conflict_message="The maintenance request could not be updated")
    db.refresh(request)
    return request