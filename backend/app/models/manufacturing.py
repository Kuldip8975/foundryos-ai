"""Manufacturing data model (Module 1).

Normalised layout:

    machines ──< machine_downtime_events
       │    └──< maintenance_requests
       └──< production_records >── products
                   └──< quality_inspections >── defect_categories

Conventions:
* integer surrogate keys; human identifiers (machine code, part number,
  defect code) are unique business keys;
* fact tables carry an optional, unique ``external_ref`` so repeated imports
  and the synthetic seed are idempotent;
* every row records its provenance in ``data_source`` (``synthetic`` marks
  demo data, which must never be presented as real company data);
* quantities are non-negative integers (discrete units); all timestamps are
  UTC (:class:`UTCDateTime`); ``production_date`` is the plant's calendar date;
* downtime duration is derived from its timestamps, never stored twice;
* invariants are enforced twice: in the service layer (clear API errors) and
  as database CHECK/FK constraints (defence in depth).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import BigIntPK, UTCDateTime, utcnow
from app.models.enums import (
    DataSource,
    DowntimeStatus,
    MaintenancePriority,
    MaintenanceStatus,
    sql_in_list,
)

CODE_LENGTH = 50
NAME_LENGTH = 200
EXTERNAL_REF_LENGTH = 100
SHIFT_LENGTH = 16
STATUS_LENGTH = 20
REASON_LENGTH = 500


def _data_source_check() -> CheckConstraint:
    return CheckConstraint(f"data_source IN ({sql_in_list(DataSource)})", name="data_source_valid")


class _Provenance:
    """Columns shared by every table: provenance and UTC audit timestamps."""

    data_source: Mapped[str] = mapped_column(
        String(STATUS_LENGTH),
        nullable=False,
        default=DataSource.MANUAL.value,
        server_default=text("'manual'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


# --------------------------------------------------------------------------- master data


class Machine(_Provenance, Base):
    __tablename__ = "machines"
    __table_args__ = (_data_source_check(),)
    business_key = "code"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    code: Mapped[str] = mapped_column(String(CODE_LENGTH), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    production_records: Mapped[list[ProductionRecord]] = relationship(back_populates="machine")
    downtime_events: Mapped[list[MachineDowntimeEvent]] = relationship(back_populates="machine")
    maintenance_requests: Mapped[list[MaintenanceRequest]] = relationship(back_populates="machine")


class Product(_Provenance, Base):
    __tablename__ = "products"
    __table_args__ = (_data_source_check(),)
    business_key = "part_number"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    part_number: Mapped[str] = mapped_column(String(CODE_LENGTH), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    production_records: Mapped[list[ProductionRecord]] = relationship(back_populates="product")


class DefectCategory(_Provenance, Base):
    __tablename__ = "defect_categories"
    __table_args__ = (_data_source_check(),)
    business_key = "code"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    code: Mapped[str] = mapped_column(String(CODE_LENGTH), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    inspections: Mapped[list[QualityInspection]] = relationship(back_populates="defect_category")


# --------------------------------------------------------------------------- facts


class ProductionRecord(_Provenance, Base):
    """Output of one product (optionally on one machine) for one date and shift."""

    __tablename__ = "production_records"
    __table_args__ = (
        CheckConstraint(
            "target_quantity >= 0 AND actual_quantity >= 0 "
            "AND accepted_quantity >= 0 AND rejected_quantity >= 0",
            name="quantities_non_negative",
        ),
        # Units not yet accepted or rejected (e.g. awaiting inspection) are allowed,
        # so the sum may be lower than actual output but never higher.
        CheckConstraint(
            "accepted_quantity + rejected_quantity <= actual_quantity",
            name="accepted_rejected_within_actual",
        ),
        _data_source_check(),
        Index("ix_production_records_date_shift", "production_date", "shift"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    external_ref: Mapped[str | None] = mapped_column(String(EXTERNAL_REF_LENGTH), unique=True)
    production_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    shift: Mapped[str] = mapped_column(String(SHIFT_LENGTH), nullable=False)
    product_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    machine_id: Mapped[int | None] = mapped_column(
        BigIntPK, ForeignKey("machines.id", ondelete="RESTRICT"), index=True
    )
    target_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product] = relationship(back_populates="production_records")
    machine: Mapped[Machine | None] = relationship(back_populates="production_records")
    inspections: Mapped[list[QualityInspection]] = relationship(
        back_populates="production_record"
    )


class QualityInspection(_Provenance, Base):
    """One inspection of a production record; one defect category per row
    (an inspection finding several defect types is recorded as several rows)."""

    __tablename__ = "quality_inspections"
    __table_args__ = (
        CheckConstraint(
            "inspected_quantity > 0 AND defect_quantity >= 0 "
            "AND defect_quantity <= inspected_quantity",
            name="quantities_valid",
        ),
        CheckConstraint(
            "defect_quantity = 0 OR defect_category_id IS NOT NULL",
            name="defect_category_required",
        ),
        _data_source_check(),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    external_ref: Mapped[str | None] = mapped_column(String(EXTERNAL_REF_LENGTH), unique=True)
    production_record_id: Mapped[int] = mapped_column(
        BigIntPK,
        ForeignKey("production_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    inspected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    inspected_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    defect_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    defect_category_id: Mapped[int | None] = mapped_column(
        BigIntPK, ForeignKey("defect_categories.id", ondelete="RESTRICT"), index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)

    production_record: Mapped[ProductionRecord] = relationship(back_populates="inspections")
    defect_category: Mapped[DefectCategory | None] = relationship(back_populates="inspections")


class MachineDowntimeEvent(_Provenance, Base):
    """A period during which a machine was not producing. ``status`` mirrors
    whether ``ended_at`` is set (enforced by a CHECK constraint)."""

    __tablename__ = "machine_downtime_events"
    __table_args__ = (
        CheckConstraint(f"status IN ({sql_in_list(DowntimeStatus)})", name="status_valid"),
        CheckConstraint(
            "(status = 'ongoing' AND ended_at IS NULL) "
            "OR (status = 'resolved' AND ended_at IS NOT NULL)",
            name="status_matches_end",
        ),
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="end_after_start"),
        _data_source_check(),
        Index("ix_machine_downtime_events_machine_started", "machine_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    external_ref: Mapped[str | None] = mapped_column(String(EXTERNAL_REF_LENGTH), unique=True)
    # Lookups by machine use the (machine_id, started_at) composite index.
    machine_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    reason: Mapped[str] = mapped_column(String(REASON_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    machine: Mapped[Machine] = relationship(back_populates="downtime_events")


class MaintenanceRequest(_Provenance, Base):
    __tablename__ = "maintenance_requests"
    __table_args__ = (
        CheckConstraint(
            f"priority IN ({sql_in_list(MaintenancePriority)})", name="priority_valid"
        ),
        CheckConstraint(f"status IN ({sql_in_list(MaintenanceStatus)})", name="status_valid"),
        CheckConstraint(
            "(status IN ('resolved', 'closed') AND resolved_at IS NOT NULL "
            "AND resolution_notes IS NOT NULL) "
            "OR (status NOT IN ('resolved', 'closed') AND resolved_at IS NULL)",
            name="resolution_consistent",
        ),
        _data_source_check(),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    external_ref: Mapped[str | None] = mapped_column(String(EXTERNAL_REF_LENGTH), unique=True)
    machine_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    issue_description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False, index=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    machine: Mapped[Machine] = relationship(back_populates="maintenance_requests")