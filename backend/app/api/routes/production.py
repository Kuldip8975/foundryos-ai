"""Production records and quality inspections (thin HTTP layer over app.services.production)."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import AwareDatetime

from app.api.auth import require
from app.api.deps import DbSession, EntityPathId, EntityQueryId, PageParams
from app.api.routes.responses import ERROR_RESPONSES
from app.api.scope import ensure_assigned, ensure_visible
from app.core.errors import BusinessRuleError
from app.core.permissions import Permission
from app.models.enums import DataSource
from app.models.manufacturing import ProductionRecord
from app.schemas.common import Page
from app.schemas.manufacturing import (
    ProductionRecordCreate,
    ProductionRecordRead,
    ProductionRecordUpdate,
    QualityInspectionCreate,
    QualityInspectionRead,
    QualityInspectionUpdate,
)
from app.services import production as service
from app.services.auth.sessions import Principal

ProductionReader = Annotated[Principal, Depends(require(Permission.PRODUCTION_READ))]
ProductionRecorder = Annotated[Principal, Depends(require(Permission.PRODUCTION_RECORD))]
QualityReader = Annotated[Principal, Depends(require(Permission.QUALITY_READ))]
QualityRecorder = Annotated[Principal, Depends(require(Permission.QUALITY_RECORD))]

production_router = APIRouter(
    prefix="/production-records", tags=["production records"], responses=ERROR_RESPONSES
)
inspections_router = APIRouter(
    prefix="/quality-inspections", tags=["quality inspections"], responses=ERROR_RESPONSES
)

ShiftQuery = Annotated[str | None, Query(min_length=1, max_length=16)]


@production_router.post(
    "", response_model=ProductionRecordRead, status_code=status.HTTP_201_CREATED
)
def create_production_record(
    payload: ProductionRecordCreate, db: DbSession, principal: ProductionRecorder
) -> Any:
    ensure_assigned(principal, payload.machine_id)
    return service.create_production_record(db, payload.values())


@production_router.get("", response_model=Page[ProductionRecordRead])
def list_production_records(
    db: DbSession,
    principal: ProductionReader,
    page: PageParams,
    date_from: Annotated[date | None, Query(description="production_date >= (inclusive)")] = None,
    date_to: Annotated[date | None, Query(description="production_date <= (inclusive)")] = None,
    shift: ShiftQuery = None,
    product_id: EntityQueryId = None,
    machine_id: EntityQueryId = None,
    data_source: Annotated[DataSource | None, Query()] = None,
) -> Any:
    filters = service.ProductionFilters(
        date_from=date_from, date_to=date_to, shift=shift, product_id=product_id,
        machine_id=machine_id, data_source=data_source, machine_ids=principal.machine_ids,
    )
    items, total = service.list_production_records(
        db, filters, limit=page.limit, offset=page.offset
    )
    return Page[ProductionRecordRead](
        items=[ProductionRecordRead.model_validate(i) for i in items],
        total=total, limit=page.limit, offset=page.offset,
    )


@production_router.get("/{record_id}", response_model=ProductionRecordRead)
def get_production_record(
    record_id: EntityPathId, db: DbSession, principal: ProductionReader
) -> Any:
    record = service.get_production_record(db, record_id)
    ensure_visible(principal, record.machine_id, "Production record", record_id)
    return record


@production_router.patch("/{record_id}", response_model=ProductionRecordRead)
def update_production_record(
    record_id: EntityPathId,
    payload: ProductionRecordUpdate,
    db: DbSession,
    principal: ProductionRecorder,
) -> Any:
    record = service.get_production_record(db, record_id)
    ensure_visible(principal, record.machine_id, "Production record", record_id)
    changes = payload.changes()
    if "machine_id" in changes:
        ensure_assigned(principal, changes["machine_id"])
    return service.update_production_record(db, record_id, changes)


def _visible_record(db: DbSession, principal: Principal, record_id: int) -> None:
    """A production record outside the scope is reported exactly like a missing one."""
    record = db.get(ProductionRecord, record_id)
    if record is not None and not principal.machine_allowed(record.machine_id):
        raise BusinessRuleError(
            f"Production record {record_id} does not exist",
            code="invalid_reference",
            details=[{"field": "production_record_id"}],
        )


@inspections_router.post(
    "", response_model=QualityInspectionRead, status_code=status.HTTP_201_CREATED
)
def create_quality_inspection(
    payload: QualityInspectionCreate, db: DbSession, principal: QualityRecorder
) -> Any:
    _visible_record(db, principal, payload.production_record_id)
    return service.create_quality_inspection(db, payload.values())


@inspections_router.get("", response_model=Page[QualityInspectionRead])
def list_quality_inspections(
    db: DbSession,
    principal: QualityReader,
    page: PageParams,
    inspected_from: Annotated[AwareDatetime | None, Query(description="Timezone required")] = None,
    inspected_to: Annotated[AwareDatetime | None, Query(description="Timezone required")] = None,
    production_record_id: EntityQueryId = None,
    defect_category_id: EntityQueryId = None,
    has_defects: Annotated[bool | None, Query()] = None,
    data_source: Annotated[DataSource | None, Query()] = None,
) -> Any:
    filters = service.InspectionFilters(
        inspected_from=inspected_from, inspected_to=inspected_to,
        production_record_id=production_record_id, defect_category_id=defect_category_id,
        has_defects=has_defects, data_source=data_source, machine_ids=principal.machine_ids,
    )
    items, total = service.list_quality_inspections(
        db, filters, limit=page.limit, offset=page.offset
    )
    return Page[QualityInspectionRead](
        items=[QualityInspectionRead.model_validate(i) for i in items],
        total=total, limit=page.limit, offset=page.offset,
    )


@inspections_router.get("/{inspection_id}", response_model=QualityInspectionRead)
def get_quality_inspection(
    inspection_id: EntityPathId, db: DbSession, principal: QualityReader
) -> Any:
    inspection = service.get_quality_inspection(db, inspection_id)
    ensure_visible(
        principal, inspection.production_record.machine_id, "Quality inspection", inspection_id
    )
    return inspection


@inspections_router.patch("/{inspection_id}", response_model=QualityInspectionRead)
def update_quality_inspection(
    inspection_id: EntityPathId,
    payload: QualityInspectionUpdate,
    db: DbSession,
    principal: QualityRecorder,
) -> Any:
    inspection = service.get_quality_inspection(db, inspection_id)
    ensure_visible(
        principal, inspection.production_record.machine_id, "Quality inspection", inspection_id
    )
    return service.update_quality_inspection(db, inspection_id, payload.changes())