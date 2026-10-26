"""Response schemas for the dashboard analytics API (Module 2).

The endpoint returns raw, additive totals (sums and counts). Ratios such as
target achievement, yield or defect rate are derived by the client from these
totals, so every figure on the dashboard can be traced back to a stored sum.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import DataSource

Granularity = Literal["day", "week", "month"]


class AppliedFilters(BaseModel):
    date_from: date | None
    date_to: date | None
    shift: str | None
    machine_id: int | None
    product_id: int | None
    data_source: DataSource | None
    utc_offset_minutes: int


class DataRange(BaseModel):
    """First and last production date matching every filter except the date range."""

    first_date: date | None
    last_date: date | None


class ProductionTotals(BaseModel):
    record_count: int
    target_quantity: int
    actual_quantity: int
    accepted_quantity: int
    rejected_quantity: int
    pending_quantity: int


class QualityTotals(BaseModel):
    """Inspections of the production records in scope."""

    inspection_count: int
    inspected_quantity: int
    defect_quantity: int


class TrendPoint(BaseModel):
    period_start: date = Field(description="First calendar day of the bucket.")
    record_count: int
    target_quantity: int
    actual_quantity: int
    accepted_quantity: int
    rejected_quantity: int
    inspected_quantity: int
    defect_quantity: int


class Trend(BaseModel):
    granularity: Granularity
    points: list[TrendPoint]


class DefectCategoryTotal(BaseModel):
    defect_category_id: int | None
    code: str | None
    name: str
    defect_quantity: int
    inspection_count: int


class MachineDowntime(BaseModel):
    machine_id: int
    code: str
    name: str
    event_count: int
    ongoing_count: int
    downtime_seconds: int


class DowntimeSummary(BaseModel):
    window_start: datetime | None = Field(description="UTC; null when no start date is set.")
    window_end: datetime = Field(description="UTC; the end date, or now if later/unset.")
    event_count: int
    ongoing_count: int
    downtime_seconds: int = Field(description="Overlap of each event with the window.")
    by_machine: list[MachineDowntime]


class MaintenanceSummary(BaseModel):
    by_status: dict[str, int] = Field(description="Current status of every request in scope.")
    open_by_priority: dict[str, int] = Field(
        description="Requests in status open or in_progress, by priority."
    )
    open_count: int
    raised_in_period: int


class DashboardSummary(BaseModel):
    generated_at: datetime
    filters: AppliedFilters
    data_range: DataRange
    shifts: list[str] = Field(description="Shift codes available for the current scope.")
    data_sources: dict[str, int] = Field(
        description="Rows in scope per provenance (production, inspections, downtime, "
        "maintenance combined). A non-zero 'synthetic' count means demo data is shown."
    )
    production: ProductionTotals
    quality: QualityTotals
    trend: Trend
    defects_by_category: list[DefectCategoryTotal]
    downtime: DowntimeSummary
    maintenance: MaintenanceSummary