"""Production records and quality inspections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError
from app.models.enums import DataSource
from app.models.manufacturing import (
    DefectCategory,
    Machine,
    Product,
    ProductionRecord,
    QualityInspection,
)
from app.services.common import (
    apply_changes,
    commit,
    ensure_date_not_future,
    ensure_not_future,
    get_or_404,
    paginate,
    require_reference,
    validate_range,
)

QUANTITY_FIELDS = ("target_quantity", "actual_quantity", "accepted_quantity", "rejected_quantity")

# --------------------------------------------------------------------------- production records


def _validate_production_quantities(actual: int, accepted: int, rejected: int) -> None:
    if accepted + rejected > actual:
        raise BusinessRuleError(
            "accepted_quantity + rejected_quantity cannot exceed actual_quantity",
            code="inconsistent_quantities",
            details=[
                {"field": "accepted_quantity"},
                {"field": "rejected_quantity"},
                {"field": "actual_quantity"},
            ],
        )


def _max_inspected_quantity(db: Session, record_id: int) -> int:
    return db.scalar(
        select(func.coalesce(func.max(QualityInspection.inspected_quantity), 0)).where(
            QualityInspection.production_record_id == record_id
        )
    ) or 0


def create_production_record(db: Session, data: dict[str, Any]) -> ProductionRecord:
    ensure_date_not_future(data["production_date"], field="production_date")
    _validate_production_quantities(
        data["actual_quantity"], data["accepted_quantity"], data["rejected_quantity"]
    )
    require_reference(
        db, Product, data["product_id"], field="product_id", label="Product", must_be_active=True
    )
    if data.get("machine_id") is not None:
        require_reference(
            db, Machine, data["machine_id"], field="machine_id", label="Machine",
            must_be_active=True,
        )
    record = ProductionRecord(**data, data_source=DataSource.MANUAL.value)
    db.add(record)
    commit(db, conflict_message="A production record with this external_ref already exists")
    db.refresh(record)
    return record


def get_production_record(db: Session, record_id: int) -> ProductionRecord:
    return get_or_404(db, ProductionRecord, record_id, "Production record")


@dataclass(frozen=True)
class ProductionFilters:
    date_from: date | None = None
    date_to: date | None = None
    shift: str | None = None
    product_id: int | None = None
    machine_id: int | None = None
    data_source: DataSource | None = None
    # Data scope: only these machines (None = every machine, including records without one).
    machine_ids: frozenset[int] | None = None


def list_production_records(
    db: Session, filters: ProductionFilters, *, limit: int, offset: int
) -> tuple[list[ProductionRecord], int]:
    validate_range(filters.date_from, filters.date_to, start_field="date_from", end_field="date_to")
    stmt = select(ProductionRecord)
    if filters.date_from is not None:
        stmt = stmt.where(ProductionRecord.production_date >= filters.date_from)
    if filters.date_to is not None:
        stmt = stmt.where(ProductionRecord.production_date <= filters.date_to)
    if filters.shift is not None:
        stmt = stmt.where(ProductionRecord.shift == filters.shift)
    if filters.product_id is not None:
        stmt = stmt.where(ProductionRecord.product_id == filters.product_id)
    if filters.machine_id is not None:
        stmt = stmt.where(ProductionRecord.machine_id == filters.machine_id)
    if filters.machine_ids is not None:
        stmt = stmt.where(ProductionRecord.machine_id.in_(sorted(filters.machine_ids)))
    if filters.data_source is not None:
        stmt = stmt.where(ProductionRecord.data_source == filters.data_source.value)
    order = (
        ProductionRecord.production_date.desc(),
        ProductionRecord.shift,
        ProductionRecord.id.desc(),
    )
    return paginate(db, stmt, order_by=order, limit=limit, offset=offset)


def update_production_record(
    db: Session, record_id: int, changes: dict[str, Any]
) -> ProductionRecord:
    record = get_production_record(db, record_id)
    if not changes:
        return record

    merged = {f: changes.get(f, getattr(record, f)) for f in QUANTITY_FIELDS}
    _validate_production_quantities(
        merged["actual_quantity"], merged["accepted_quantity"], merged["rejected_quantity"]
    )
    if "production_date" in changes:
        ensure_date_not_future(changes["production_date"], field="production_date")
    if "product_id" in changes and changes["product_id"] != record.product_id:
        require_reference(
            db, Product, changes["product_id"], field="product_id", label="Product",
            must_be_active=True,
        )
    if changes.get("machine_id") is not None and changes["machine_id"] != record.machine_id:
        require_reference(
            db, Machine, changes["machine_id"], field="machine_id", label="Machine",
            must_be_active=True,
        )
    if "actual_quantity" in changes:
        largest_inspection = _max_inspected_quantity(db, record.id)
        if merged["actual_quantity"] < largest_inspection:
            raise BusinessRuleError(
                f"actual_quantity cannot be lower than an existing inspection's "
                f"inspected_quantity ({largest_inspection})",
                code="inconsistent_quantities",
                details=[{"field": "actual_quantity"}],
            )

    apply_changes(record, changes)
    commit(db, conflict_message="The production record could not be updated")
    db.refresh(record)
    return record


# --------------------------------------------------------------------------- quality inspections


def _validate_inspection(
    db: Session,
    *,
    record: ProductionRecord,
    inspected_quantity: int,
    defect_quantity: int,
    defect_category_id: int | None,
    check_category: bool,
) -> None:
    if inspected_quantity > record.actual_quantity:
        raise BusinessRuleError(
            "inspected_quantity cannot exceed the production record's actual_quantity "
            f"({record.actual_quantity})",
            code="inconsistent_quantities",
            details=[{"field": "inspected_quantity"}],
        )
    if defect_quantity > inspected_quantity:
        raise BusinessRuleError(
            "defect_quantity cannot exceed inspected_quantity",
            code="inconsistent_quantities",
            details=[{"field": "defect_quantity"}],
        )
    if defect_quantity > 0 and defect_category_id is None:
        raise BusinessRuleError(
            "defect_category_id is required when defect_quantity is greater than 0",
            code="defect_category_required",
            details=[{"field": "defect_category_id"}],
        )
    if check_category and defect_category_id is not None:
        require_reference(
            db, DefectCategory, defect_category_id, field="defect_category_id",
            label="Defect category", must_be_active=True,
        )


def create_quality_inspection(db: Session, data: dict[str, Any]) -> QualityInspection:
    ensure_not_future(data["inspected_at"], field="inspected_at")
    record = require_reference(
        db, ProductionRecord, data["production_record_id"],
        field="production_record_id", label="Production record",
    )
    _validate_inspection(
        db,
        record=record,
        inspected_quantity=data["inspected_quantity"],
        defect_quantity=data["defect_quantity"],
        defect_category_id=data.get("defect_category_id"),
        check_category=True,
    )
    inspection = QualityInspection(**data, data_source=DataSource.MANUAL.value)
    db.add(inspection)
    commit(db, conflict_message="A quality inspection with this external_ref already exists")
    db.refresh(inspection)
    return inspection


def get_quality_inspection(db: Session, inspection_id: int) -> QualityInspection:
    return get_or_404(db, QualityInspection, inspection_id, "Quality inspection")


@dataclass(frozen=True)
class InspectionFilters:
    inspected_from: datetime | None = None
    inspected_to: datetime | None = None
    production_record_id: int | None = None
    defect_category_id: int | None = None
    has_defects: bool | None = None
    data_source: DataSource | None = None
    # Data scope: inspections of production records on these machines (None = all).
    machine_ids: frozenset[int] | None = None


def list_quality_inspections(
    db: Session, filters: InspectionFilters, *, limit: int, offset: int
) -> tuple[list[QualityInspection], int]:
    validate_range(
        filters.inspected_from, filters.inspected_to,
        start_field="inspected_from", end_field="inspected_to",
    )
    stmt = select(QualityInspection)
    if filters.inspected_from is not None:
        stmt = stmt.where(QualityInspection.inspected_at >= filters.inspected_from)
    if filters.inspected_to is not None:
        stmt = stmt.where(QualityInspection.inspected_at <= filters.inspected_to)
    if filters.production_record_id is not None:
        stmt = stmt.where(QualityInspection.production_record_id == filters.production_record_id)
    if filters.defect_category_id is not None:
        stmt = stmt.where(QualityInspection.defect_category_id == filters.defect_category_id)
    if filters.has_defects is True:
        stmt = stmt.where(QualityInspection.defect_quantity > 0)
    elif filters.has_defects is False:
        stmt = stmt.where(QualityInspection.defect_quantity == 0)
    if filters.data_source is not None:
        stmt = stmt.where(QualityInspection.data_source == filters.data_source.value)
    if filters.machine_ids is not None:
        stmt = stmt.join(
            ProductionRecord, QualityInspection.production_record_id == ProductionRecord.id
        ).where(ProductionRecord.machine_id.in_(sorted(filters.machine_ids)))
    order = (QualityInspection.inspected_at.desc(), QualityInspection.id.desc())
    return paginate(db, stmt, order_by=order, limit=limit, offset=offset)


def update_quality_inspection(
    db: Session, inspection_id: int, changes: dict[str, Any]
) -> QualityInspection:
    inspection = get_quality_inspection(db, inspection_id)
    if not changes:
        return inspection
    if "inspected_at" in changes:
        ensure_not_future(changes["inspected_at"], field="inspected_at")
    category_id = changes.get("defect_category_id", inspection.defect_category_id)
    _validate_inspection(
        db,
        record=inspection.production_record,
        inspected_quantity=changes.get("inspected_quantity", inspection.inspected_quantity),
        defect_quantity=changes.get("defect_quantity", inspection.defect_quantity),
        defect_category_id=category_id,
        check_category=(
            "defect_category_id" in changes and category_id != inspection.defect_category_id
        ),
    )
    apply_changes(inspection, changes)
    commit(db, conflict_message="The quality inspection could not be updated")
    db.refresh(inspection)
    return inspection