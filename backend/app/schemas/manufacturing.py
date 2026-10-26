"""Request/response schemas for the manufacturing data API (Module 1).

Field-level rules (types, lengths, non-negative quantities, timezone-aware
timestamps) are enforced here. Cross-field and cross-record rules
(quantity consistency, date ranges, references, status transitions) are
enforced in ``app.services`` so create and update share one implementation.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from pydantic import AwareDatetime, Field, StringConstraints, computed_field

from app.models.enums import DataSource, DowntimeStatus, MaintenancePriority, MaintenanceStatus
from app.schemas.common import (
    Code,
    EntityId,
    ExternalRef,
    InputModel,
    LongText,
    Name,
    PatchModel,
    PositiveQuantity,
    Quantity,
    ReadModel,
)

Shift = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=16, pattern=r"^[A-Za-z0-9_-]+$"
    ),
]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


# --------------------------------------------------------------------------- master data


class _MasterRead(ReadModel):
    id: int
    name: str
    description: str | None
    is_active: bool
    data_source: DataSource
    created_at: datetime
    updated_at: datetime


class _MasterUpdate(PatchModel):
    """The business key (code / part number) is immutable once created."""

    non_nullable_fields = frozenset({"name", "is_active"})

    name: Name | None = None
    description: LongText | None = None
    is_active: bool | None = None


class MachineCreate(InputModel):
    code: Code
    name: Name
    description: LongText | None = None
    is_active: bool = True


class MachineUpdate(_MasterUpdate):
    pass


class MachineRead(_MasterRead):
    code: str


class ProductCreate(InputModel):
    part_number: Code
    name: Name
    description: LongText | None = None
    is_active: bool = True


class ProductUpdate(_MasterUpdate):
    pass


class ProductRead(_MasterRead):
    part_number: str


class DefectCategoryCreate(InputModel):
    code: Code
    name: Name
    description: LongText | None = None
    is_active: bool = True


class DefectCategoryUpdate(_MasterUpdate):
    pass


class DefectCategoryRead(_MasterRead):
    code: str


# --------------------------------------------------------------------------- production


class ProductionRecordCreate(InputModel):
    production_date: date
    shift: Shift
    product_id: EntityId
    machine_id: EntityId | None = None
    target_quantity: Quantity
    actual_quantity: Quantity
    accepted_quantity: Quantity
    rejected_quantity: Quantity
    notes: LongText | None = None
    external_ref: ExternalRef | None = None


class ProductionRecordUpdate(PatchModel):
    non_nullable_fields = frozenset(
        {
            "production_date",
            "shift",
            "product_id",
            "target_quantity",
            "actual_quantity",
            "accepted_quantity",
            "rejected_quantity",
        }
    )

    production_date: date | None = None
    shift: Shift | None = None
    product_id: EntityId | None = None
    machine_id: EntityId | None = None
    target_quantity: Quantity | None = None
    actual_quantity: Quantity | None = None
    accepted_quantity: Quantity | None = None
    rejected_quantity: Quantity | None = None
    notes: LongText | None = None


class ProductionRecordRead(ReadModel):
    id: int
    external_ref: str | None
    production_date: date
    shift: str
    product_id: int
    machine_id: int | None
    target_quantity: int
    actual_quantity: int
    accepted_quantity: int
    rejected_quantity: int
    notes: str | None
    data_source: DataSource
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pending_quantity(self) -> int:
        """Units produced but not yet accepted or rejected."""
        return self.actual_quantity - self.accepted_quantity - self.rejected_quantity


# --------------------------------------------------------------------------- quality


class QualityInspectionCreate(InputModel):
    production_record_id: EntityId
    inspected_at: AwareDatetime
    inspected_quantity: PositiveQuantity
    defect_quantity: Quantity
    defect_category_id: EntityId | None = None
    notes: LongText | None = None
    external_ref: ExternalRef | None = None


class QualityInspectionUpdate(PatchModel):
    """The production reference is immutable; record a new inspection instead."""

    non_nullable_fields = frozenset({"inspected_at", "inspected_quantity", "defect_quantity"})

    inspected_at: AwareDatetime | None = None
    inspected_quantity: PositiveQuantity | None = None
    defect_quantity: Quantity | None = None
    defect_category_id: EntityId | None = None
    notes: LongText | None = None


class QualityInspectionRead(ReadModel):
    id: int
    external_ref: str | None
    production_record_id: int
    inspected_at: datetime
    inspected_quantity: int
    defect_quantity: int
    defect_category_id: int | None
    notes: str | None
    data_source: DataSource
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- downtime


class DowntimeEventCreate(InputModel):
    """``status`` is derived: ``ongoing`` without ``ended_at``, else ``resolved``."""

    machine_id: EntityId
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    reason: Reason
    notes: LongText | None = None
    external_ref: ExternalRef | None = None


class DowntimeEventUpdate(PatchModel):
    """Set ``ended_at`` to resolve an ongoing event. A resolved event cannot be reopened."""

    non_nullable_fields = frozenset({"started_at", "reason"})

    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    reason: Reason | None = None
    notes: LongText | None = None


class DowntimeEventRead(ReadModel):
    id: int
    external_ref: str | None
    machine_id: int
    started_at: datetime
    ended_at: datetime | None
    status: DowntimeStatus
    reason: str
    notes: str | None
    data_source: DataSource
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration_seconds(self) -> int | None:
        """Derived from the timestamps; ``null`` while the event is ongoing."""
        if self.ended_at is None:
            return None
        return int((self.ended_at - self.started_at).total_seconds())


# --------------------------------------------------------------------------- maintenance


class MaintenanceRequestCreate(InputModel):
    """New requests always start in status ``open``."""

    machine_id: EntityId
    issue_description: LongText
    priority: MaintenancePriority = MaintenancePriority.MEDIUM
    external_ref: ExternalRef | None = None


class MaintenanceRequestUpdate(PatchModel):
    """Status changes follow MAINTENANCE_TRANSITIONS; moving to ``resolved``
    requires ``resolution_notes`` (in this request or already stored)."""

    non_nullable_fields = frozenset({"issue_description", "priority", "status"})

    issue_description: LongText | None = None
    priority: MaintenancePriority | None = None
    status: MaintenanceStatus | None = None
    resolution_notes: LongText | None = None


class MaintenanceRequestRead(ReadModel):
    id: int
    external_ref: str | None
    machine_id: int
    issue_description: str
    priority: MaintenancePriority
    status: MaintenanceStatus
    resolution_notes: str | None
    resolved_at: datetime | None
    data_source: DataSource
    created_at: datetime = Field(description="When the request was raised (UTC).")
    updated_at: datetime