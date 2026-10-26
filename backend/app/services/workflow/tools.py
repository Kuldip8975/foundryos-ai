"""The workflow agent's tools (Module 4) — the complete allowlist.

Each tool has a name, a strict Pydantic argument model, the permission it
needs and a handler written here in Python. The model can only *name* a tool
and supply arguments; it never supplies SQL, code, table names or URLs. A tool
name that is not in :data:`TOOLS` is refused.

Read tools return bounded, JSON-serialisable summaries (row caps, truncated
free text). ``prepare_maintenance_request`` is the only tool related to a
change and it changes nothing: it validates the request and returns a preview
that becomes an approval proposal.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from app.models.enums import DataSource, MaintenanceStatus
from app.models.manufacturing import (
    Machine,
    MachineDowntimeEvent,
    MaintenanceRequest,
    ProductionRecord,
)
from app.schemas.workflow import (
    DowntimeArgs,
    MachineStatusArgs,
    MaintenanceListArgs,
    PrepareMaintenanceArgs,
    ProductionQualityArgs,
)
from app.services import analytics
from app.services.operations import MaintenanceFilters, list_maintenance_requests
from app.services.workflow.permissions import Permission

MAX_MACHINES = 50
MAX_DOWNTIME_EVENTS = 20
MAX_TOP_DEFECTS = 5
REASON_CHARS = 160
ISSUE_CHARS = 200
TOOL_STATEMENT_TIMEOUT_MS = 5000
OPEN_STATUSES = (MaintenanceStatus.OPEN.value, MaintenanceStatus.IN_PROGRESS.value)


class ToolError(Exception):
    """A tool ran but its input broke a business rule. The message is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


Handler = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    permission: Permission
    prepares_change: bool
    handler: Handler
    # True when the tool can answer for "all machines" and must then be limited
    # to a machine-scoped person's machines (handler accepts ``only_codes``).
    # Every other tool needs an explicit machine_code from such a person.
    lists_machines: bool = False


# --------------------------------------------------------------------------- helpers


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())  # collapse newlines: records are data, not layout
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _machine_by_code(db: Session, code: str) -> Machine:
    machine = db.scalar(select(Machine).where(Machine.code == code))
    if machine is None:
        raise ToolError("unknown_machine", f"No machine has the code {code!r}.")
    return machine


def _not_future(day: date, field: str) -> None:
    # Plants may be ahead of UTC, so allow "tomorrow" in UTC terms.
    if day > datetime.now(UTC).date() + timedelta(days=1):
        raise ToolError("future_date", f"{field} cannot be in the future.")


def _sources(rows: list[Any]) -> dict[str, int]:
    counts = dict.fromkeys((s.value for s in DataSource), 0)
    for source, count in rows:
        counts[source] = counts.get(source, 0) + int(count or 0)
    return counts


def limit_statement_time(db: Session) -> None:
    """Bound each tool query on PostgreSQL (no effect on SQLite in tests)."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text(f"SET LOCAL statement_timeout = {TOOL_STATEMENT_TIMEOUT_MS}"))


# --------------------------------------------------------------------------- read tools


def _machine_state(machine: Machine, has_ongoing_downtime: bool) -> str:
    if has_ongoing_downtime:
        return "down"
    return "running" if machine.is_active else "inactive"


def machine_status(
    db: Session,
    args: MachineStatusArgs,
    now: datetime,
    only_codes: frozenset[str] | None = None,
) -> dict[str, Any]:
    stmt = select(Machine).order_by(Machine.code).limit(MAX_MACHINES + 1)
    if only_codes is not None:  # data scope (an operator's assigned machines)
        stmt = stmt.where(Machine.code.in_(sorted(only_codes)))
    if args.machine_code is not None:
        stmt = select(Machine).where(Machine.id == _machine_by_code(db, args.machine_code).id)
    machines = list(db.scalars(stmt))
    truncated = len(machines) > MAX_MACHINES
    machines = machines[:MAX_MACHINES]
    ids = [m.id for m in machines]

    ongoing: dict[int, dict[str, Any]] = {}
    open_counts: dict[int, int] = {}
    if ids:
        for machine_id, started_at, reason in db.execute(
            select(
                MachineDowntimeEvent.machine_id,
                MachineDowntimeEvent.started_at,
                MachineDowntimeEvent.reason,
            )
            .where(
                MachineDowntimeEvent.ended_at.is_(None),
                MachineDowntimeEvent.machine_id.in_(ids),
            )
            .order_by(MachineDowntimeEvent.started_at)
        ).all():
            ongoing.setdefault(
                machine_id,
                {
                    "started_at": _iso(started_at),
                    "minutes_so_far": max(0, int((now - started_at).total_seconds() // 60)),
                    "reason": _clip(reason, REASON_CHARS),
                },
            )
        for machine_id, count in db.execute(
            select(MaintenanceRequest.machine_id, func.count(MaintenanceRequest.id))
            .where(
                MaintenanceRequest.status.in_(OPEN_STATUSES),
                MaintenanceRequest.machine_id.in_(ids),
            )
            .group_by(MaintenanceRequest.machine_id)
        ).all():
            open_counts[machine_id] = int(count)

    return {
        "machines": [
            {
                "code": m.code,
                "name": m.name,
                "is_active": m.is_active,
                "state": _machine_state(m, m.id in ongoing),
                "ongoing_downtime": ongoing.get(m.id),
                "open_maintenance_requests": open_counts.get(m.id, 0),
            }
            for m in machines
        ],
        "machine_count": len(machines),
        "truncated": truncated,
        "data_sources": _sources([(m.data_source, 1) for m in machines]),
        "note": "state 'running' means no ongoing downtime is recorded, not live telemetry.",
    }


def downtime(db: Session, args: DowntimeArgs, now: datetime) -> dict[str, Any]:
    _not_future(args.date_from, "date_from")
    machine_id = _machine_by_code(db, args.machine_code).id if args.machine_code else None
    filters = analytics.DashboardFilters(
        date_from=args.date_from,
        date_to=args.date_to,
        machine_id=machine_id,
        utc_offset_minutes=args.utc_offset_minutes,
    )
    summary = analytics._downtime(db, filters, now)  # noqa: SLF001 - shared Module 2 rules
    start, end, _nominal = analytics._window(filters, now)  # noqa: SLF001

    conditions = [MachineDowntimeEvent.started_at < end]
    if start is not None:
        conditions.append(
            or_(MachineDowntimeEvent.ended_at.is_(None), MachineDowntimeEvent.ended_at > start)
        )
    if machine_id is not None:
        conditions.append(MachineDowntimeEvent.machine_id == machine_id)
    if args.status is not None:
        conditions.append(MachineDowntimeEvent.status == args.status.value)

    rows = db.execute(
        select(MachineDowntimeEvent, Machine.code)
        .join(Machine, MachineDowntimeEvent.machine_id == Machine.id)
        .where(and_(*conditions))
        .order_by(MachineDowntimeEvent.started_at.desc(), MachineDowntimeEvent.id.desc())
        .limit(MAX_DOWNTIME_EVENTS + 1)
    ).all()
    sources = db.execute(
        select(MachineDowntimeEvent.data_source, func.count(MachineDowntimeEvent.id))
        .where(and_(*conditions))
        .group_by(MachineDowntimeEvent.data_source)
    ).all()

    return {
        "window_start": _iso(summary["window_start"]),
        "window_end": _iso(summary["window_end"]),
        "event_count": summary["event_count"],
        "ongoing_count": summary["ongoing_count"],
        "downtime_minutes": round(summary["downtime_seconds"] / 60, 1),
        "by_machine": [
            {
                "code": item["code"],
                "name": item["name"],
                "event_count": item["event_count"],
                "ongoing_count": item["ongoing_count"],
                "downtime_minutes": round(item["downtime_seconds"] / 60, 1),
            }
            for item in summary["by_machine"]
        ],
        "recent_events": [
            {
                "machine_code": code,
                "started_at": _iso(event.started_at),
                "ended_at": _iso(event.ended_at),
                "status": event.status,
                "reason": _clip(event.reason, REASON_CHARS),
            }
            for event, code in rows[:MAX_DOWNTIME_EVENTS]
        ],
        "recent_events_truncated": len(rows) > MAX_DOWNTIME_EVENTS,
        "data_sources": _sources(list(sources)),
        "rules": "minutes count only the overlap with the window; ongoing events count up to now",
    }


def production_quality(db: Session, args: ProductionQualityArgs, now: datetime) -> dict[str, Any]:
    _not_future(args.date_from, "date_from")
    machine_id = _machine_by_code(db, args.machine_code).id if args.machine_code else None
    filters = analytics.DashboardFilters(
        date_from=args.date_from, date_to=args.date_to, shift=args.shift, machine_id=machine_id
    )
    production = analytics._production_totals(db, filters)  # noqa: SLF001
    quality = analytics._quality_totals(db, filters)  # noqa: SLF001
    defects = analytics._defects_by_category(db, filters)[:MAX_TOP_DEFECTS]  # noqa: SLF001
    sources = db.execute(
        select(ProductionRecord.data_source, func.count(ProductionRecord.id))
        .where(*analytics._record_conditions(filters))  # noqa: SLF001
        .group_by(ProductionRecord.data_source)
    ).all()
    actual = production["actual_quantity"]
    return {
        "production": production,
        "quality": quality,
        "ratios": {
            "target_achievement": _ratio(actual, production["target_quantity"]),
            "rejection_rate": _ratio(production["rejected_quantity"], actual),
            "first_pass_yield": _ratio(
                production["accepted_quantity"],
                production["accepted_quantity"] + production["rejected_quantity"],
            ),
            "defect_rate": _ratio(quality["defect_quantity"], quality["inspected_quantity"]),
        },
        "top_defect_categories": [
            {"code": d["code"], "name": d["name"], "defect_quantity": d["defect_quantity"]}
            for d in defects
        ],
        "data_sources": _sources(list(sources)),
        "definitions": {
            "target_achievement": "actual / target",
            "rejection_rate": "rejected / actual",
            "first_pass_yield": "accepted / (accepted + rejected)",
            "defect_rate": "defects / inspected units",
            "null": "not available (zero denominator)",
        },
    }


def maintenance_list(db: Session, args: MaintenanceListArgs, now: datetime) -> dict[str, Any]:
    machine_id = _machine_by_code(db, args.machine_code).id if args.machine_code else None
    items, total = list_maintenance_requests(
        db,
        MaintenanceFilters(machine_id=machine_id, status=args.status, priority=args.priority),
        limit=args.limit,
        offset=0,
    )
    codes = dict(
        db.execute(
            select(Machine.id, Machine.code).where(
                Machine.id.in_(sorted({i.machine_id for i in items}))
            )
        ).all()
    ) if items else {}
    return {
        "total": total,
        "items": [
            {
                "id": item.id,
                "machine_code": codes.get(item.machine_id),
                "priority": item.priority,
                "status": item.status,
                "created_at": _iso(item.created_at),
                "issue_description": _clip(item.issue_description, ISSUE_CHARS),
                "data_source": item.data_source,
            }
            for item in items
        ],
        "truncated": total > len(items),
        "data_sources": _sources([(item.data_source, 1) for item in items]),
    }


# --------------------------------------------------------------------------- change preparation


def prepare_maintenance(
    db: Session, args: PrepareMaintenanceArgs, now: datetime
) -> dict[str, Any]:
    """Validate a maintenance request and describe it. Writes nothing."""
    machine = _machine_by_code(db, args.machine_code)
    if not machine.is_active:
        raise ToolError(
            "inactive_machine", f"Machine {machine.code} is inactive; requests cannot be raised."
        )
    similar_open = db.scalar(
        select(func.count(MaintenanceRequest.id)).where(
            MaintenanceRequest.machine_id == machine.id,
            MaintenanceRequest.status.in_(OPEN_STATUSES),
        )
    )
    return {
        "action": "create_maintenance_request",
        "target": {"machine_id": machine.id},
        "machine_code": machine.code,
        "machine_name": machine.name,
        "priority": args.priority.value,
        "issue_description": args.issue_description,
        "initial_status": MaintenanceStatus.OPEN.value,
        "open_requests_for_machine": int(similar_open or 0),
        "requires_approval": True,
    }


# --------------------------------------------------------------------------- registry

PREPARE_MAINTENANCE_REQUEST = "prepare_maintenance_request"

TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            name="get_machine_status",
            description=(
                "Machines with their recorded state: ongoing downtime (if any) and the number "
                "of open maintenance requests. Optional machine_code narrows to one machine."
            ),
            args_model=MachineStatusArgs,
            permission=Permission.READ_DATA,
            prepares_change=False,
            handler=machine_status,
            lists_machines=True,
        ),
        ToolSpec(
            name="query_downtime",
            description=(
                "Downtime between two plant dates (max 31 days): totals, minutes per machine and "
                "up to 20 recent events with their reasons."
            ),
            args_model=DowntimeArgs,
            permission=Permission.READ_DATA,
            prepares_change=False,
            handler=downtime,
        ),
        ToolSpec(
            name="get_production_quality_metrics",
            description=(
                "Production and quality totals and ratios between two plant dates (max 92 days), "
                "optionally for one machine or shift, with the top defect categories."
            ),
            args_model=ProductionQualityArgs,
            permission=Permission.READ_DATA,
            prepares_change=False,
            handler=production_quality,
        ),
        ToolSpec(
            name="list_maintenance_requests",
            description=(
                "Maintenance requests, newest first (max 20), filtered by machine, status "
                "or priority."
            ),
            args_model=MaintenanceListArgs,
            permission=Permission.READ_DATA,
            prepares_change=False,
            handler=maintenance_list,
        ),
        ToolSpec(
            name=PREPARE_MAINTENANCE_REQUEST,
            description=(
                "Prepare a NEW maintenance request for human approval. It does not create "
                "anything: a supervisor must approve it before it is recorded. At most one per "
                "conversation."
            ),
            args_model=PrepareMaintenanceArgs,
            permission=Permission.PROPOSE_MAINTENANCE,
            prepares_change=True,
            handler=prepare_maintenance,
        ),
    )
}