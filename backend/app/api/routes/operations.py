"""Machine downtime and maintenance requests (thin HTTP layer over app.services.operations)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import AwareDatetime

from app.api.auth import require
from app.api.deps import DbSession, EntityPathId, EntityQueryId, PageParams
from app.api.routes.responses import ERROR_RESPONSES
from app.api.scope import ensure_assigned, ensure_visible
from app.core.permissions import Permission
from app.models.enums import DataSource, DowntimeStatus, MaintenancePriority, MaintenanceStatus
from app.schemas.common import Page
from app.schemas.manufacturing import (
    DowntimeEventCreate,
    DowntimeEventRead,
    DowntimeEventUpdate,
    MaintenanceRequestCreate,
    MaintenanceRequestRead,
    MaintenanceRequestUpdate,
)
from app.services import operations as service
from app.services.auth.sessions import Principal

DowntimeReader = Annotated[Principal, Depends(require(Permission.DOWNTIME_READ))]
DowntimeRecorder = Annotated[Principal, Depends(require(Permission.DOWNTIME_RECORD))]
MaintenanceReader = Annotated[Principal, Depends(require(Permission.MAINTENANCE_READ))]
# Direct changes bypass the assistant's approval flow, so only supervisors may make them;
# operators prepare maintenance requests through the workflow assistant instead.
MaintenanceManager = Annotated[Principal, Depends(require(Permission.MAINTENANCE_MANAGE))]

downtime_router = APIRouter(
    prefix="/downtime-events", tags=["machine downtime"], responses=ERROR_RESPONSES
)
maintenance_router = APIRouter(
    prefix="/maintenance-requests", tags=["maintenance requests"], responses=ERROR_RESPONSES
)

AwareQuery = Annotated[AwareDatetime | None, Query(description="Timezone required")]


@downtime_router.post("", response_model=DowntimeEventRead, status_code=status.HTTP_201_CREATED)
def create_downtime_event(
    payload: DowntimeEventCreate, db: DbSession, principal: DowntimeRecorder
) -> Any:
    ensure_assigned(principal, payload.machine_id)
    return service.create_downtime_event(db, payload.values())


@downtime_router.get("", response_model=Page[DowntimeEventRead])
def list_downtime_events(
    db: DbSession,
    principal: DowntimeReader,
    page: PageParams,
    started_from: AwareQuery = None,
    started_to: AwareQuery = None,
    machine_id: EntityQueryId = None,
    status_: Annotated[DowntimeStatus | None, Query(alias="status")] = None,
    data_source: Annotated[DataSource | None, Query()] = None,
) -> Any:
    filters = service.DowntimeFilters(
        started_from=started_from, started_to=started_to, machine_id=machine_id,
        status=status_, data_source=data_source, machine_ids=principal.machine_ids,
    )
    items, total = service.list_downtime_events(db, filters, limit=page.limit, offset=page.offset)
    return Page[DowntimeEventRead](
        items=[DowntimeEventRead.model_validate(i) for i in items],
        total=total, limit=page.limit, offset=page.offset,
    )


@downtime_router.get("/{event_id}", response_model=DowntimeEventRead)
def get_downtime_event(event_id: EntityPathId, db: DbSession, principal: DowntimeReader) -> Any:
    event = service.get_downtime_event(db, event_id)
    ensure_visible(principal, event.machine_id, "Downtime event", event_id)
    return event


@downtime_router.patch("/{event_id}", response_model=DowntimeEventRead)
def update_downtime_event(
    event_id: EntityPathId,
    payload: DowntimeEventUpdate,
    db: DbSession,
    principal: DowntimeRecorder,
) -> Any:
    event = service.get_downtime_event(db, event_id)
    ensure_visible(principal, event.machine_id, "Downtime event", event_id)
    return service.update_downtime_event(db, event_id, payload.changes())


@maintenance_router.post(
    "", response_model=MaintenanceRequestRead, status_code=status.HTTP_201_CREATED
)
def create_maintenance_request(
    payload: MaintenanceRequestCreate, db: DbSession, principal: MaintenanceManager
) -> Any:
    ensure_assigned(principal, payload.machine_id)
    return service.create_maintenance_request(db, payload.values())


@maintenance_router.get("", response_model=Page[MaintenanceRequestRead])
def list_maintenance_requests(
    db: DbSession,
    principal: MaintenanceReader,
    page: PageParams,
    created_from: AwareQuery = None,
    created_to: AwareQuery = None,
    machine_id: EntityQueryId = None,
    status_: Annotated[MaintenanceStatus | None, Query(alias="status")] = None,
    priority: Annotated[MaintenancePriority | None, Query()] = None,
    data_source: Annotated[DataSource | None, Query()] = None,
) -> Any:
    filters = service.MaintenanceFilters(
        created_from=created_from, created_to=created_to, machine_id=machine_id,
        status=status_, priority=priority, data_source=data_source,
        machine_ids=principal.machine_ids,
    )
    items, total = service.list_maintenance_requests(
        db, filters, limit=page.limit, offset=page.offset
    )
    return Page[MaintenanceRequestRead](
        items=[MaintenanceRequestRead.model_validate(i) for i in items],
        total=total, limit=page.limit, offset=page.offset,
    )


@maintenance_router.get("/{request_id}", response_model=MaintenanceRequestRead)
def get_maintenance_request(
    request_id: EntityPathId, db: DbSession, principal: MaintenanceReader
) -> Any:
    request = service.get_maintenance_request(db, request_id)
    ensure_visible(principal, request.machine_id, "Maintenance request", request_id)
    return request


@maintenance_router.patch("/{request_id}", response_model=MaintenanceRequestRead)
def update_maintenance_request(
    request_id: EntityPathId,
    payload: MaintenanceRequestUpdate,
    db: DbSession,
    principal: MaintenanceManager,
) -> Any:
    request = service.get_maintenance_request(db, request_id)
    ensure_visible(principal, request.machine_id, "Maintenance request", request_id)
    return service.update_maintenance_request(db, request_id, payload.changes())