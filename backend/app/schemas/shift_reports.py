"""Schemas for shift analysis and AI shift reports (Module 3).

Three groups:
* request models (validated user input);
* ``ShiftMetrics`` — the deterministic, database-derived figures. These are
  the source of truth; the AI report may only interpret them;
* ``AiShiftReport`` — the structure the language model must return. It is
  validated strictly: unknown fields are rejected and every finding and
  recommendation must cite evidence keys that exist in the metrics snapshot.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.models.enums import DataSource, ReportStatus
from app.schemas.common import InputModel, ReadModel
from app.schemas.manufacturing import Shift

MAX_WINDOW = timedelta(hours=24)


# --------------------------------------------------------------------------- requests


class ShiftScopeIn(InputModel):
    """One shift: a plant calendar date and shift code, optionally with its
    UTC time window (needed for downtime and maintenance-in-window figures)."""

    production_date: date
    shift: Shift
    window_start: AwareDatetime | None = None
    window_end: AwareDatetime | None = None
    data_source: DataSource | None = None

    @model_validator(mode="after")
    def _check_window(self) -> ShiftScopeIn:
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("window_start and window_end must be given together")
        if self.window_start is not None and self.window_end is not None:
            if self.window_end <= self.window_start:
                raise ValueError("window_end must be after window_start")
            if self.window_end - self.window_start > MAX_WINDOW:
                raise ValueError("a shift window cannot be longer than 24 hours")
        return self


class ShiftReportCreate(ShiftScopeIn):
    regenerate: bool = Field(
        default=False,
        description="Generate a new report even if one exists for identical data.",
    )


# --------------------------------------------------------------------------- deterministic metrics


class ProductionTotals(BaseModel):
    record_count: int
    target_quantity: int
    actual_quantity: int
    accepted_quantity: int
    rejected_quantity: int
    pending_quantity: int
    target_achievement: float | None = Field(description="actual ÷ target; null if target is 0")
    rejection_rate: float | None = Field(description="rejected ÷ actual; null if actual is 0")
    first_pass_yield: float | None = Field(
        description="accepted ÷ (accepted + rejected); null if none decided"
    )


class MachineProduction(BaseModel):
    machine: str = Field(description="Machine code, or 'Unassigned'")
    record_count: int
    target_quantity: int
    actual_quantity: int
    rejected_quantity: int
    target_achievement: float | None
    rejection_rate: float | None


class QualityTotals(BaseModel):
    inspection_count: int
    inspected_quantity: int
    defect_quantity: int
    defect_rate: float | None = Field(description="defects ÷ inspected; null if none inspected")


class DefectCategoryCount(BaseModel):
    category: str
    defect_quantity: int
    inspection_count: int


class MachineDowntime(BaseModel):
    machine: str
    event_count: int
    ongoing_count: int
    downtime_seconds: int


class DowntimeReason(BaseModel):
    reason: str
    event_count: int
    downtime_seconds: int


class DowntimeTotals(BaseModel):
    available: bool = Field(description="False when no shift window was given")
    event_count: int | None
    ongoing_count: int | None
    downtime_seconds: int | None
    by_machine: list[MachineDowntime]
    top_reasons: list[DowntimeReason]


class MaintenanceTotals(BaseModel):
    raised_in_window: int | None = Field(description="Null when no shift window was given")
    open_now: int = Field(description="Current open + in-progress requests (not as of the shift)")
    open_now_by_priority: dict[str, int]


class PreviousShift(BaseModel):
    production_date: date
    production: ProductionTotals
    quality: QualityTotals
    downtime_seconds: int | None


class ShiftComparison(BaseModel):
    """This shift minus the previous comparable shift (same shift code)."""

    actual_quantity_change: int
    target_achievement_change: float | None
    rejection_rate_change: float | None
    defect_rate_change: float | None
    downtime_seconds_change: int | None


class ShiftMetrics(BaseModel):
    production_date: date
    shift: str
    window_start: datetime | None
    window_end: datetime | None
    data_source_filter: DataSource | None
    data_sources: dict[str, int]
    production: ProductionTotals
    production_by_machine: list[MachineProduction]
    quality: QualityTotals
    defects_by_category: list[DefectCategoryCount]
    downtime: DowntimeTotals
    maintenance: MaintenanceTotals
    previous: PreviousShift | None
    comparison: ShiftComparison | None
    limitations: list[str]


# --------------------------------------------------------------------------- AI output

Statement = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
EvidenceKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Evidence = Annotated[list[EvidenceKey], Field(min_length=1, max_length=8)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_evidence(keys: list[str], info: ValidationInfo) -> list[str]:
    allowed = (info.context or {}).get("allowed_evidence")
    if allowed is None:
        return keys  # stored reports are re-read without context
    unknown = sorted(set(keys) - set(allowed))
    if unknown:
        raise ValueError(f"evidence cites unknown metric keys: {', '.join(unknown[:5])}")
    return keys


class Finding(_Strict):
    statement: Statement
    kind: Literal["measured_fact", "possible_explanation"] = Field(
        description="measured_fact: restates the metrics; possible_explanation: a hypothesis"
    )
    evidence: Evidence

    @field_validator("evidence")
    @classmethod
    def _evidence_exists(cls, value: list[str], info: ValidationInfo) -> list[str]:
        return _check_evidence(value, info)


class Recommendation(_Strict):
    priority: Literal["high", "medium", "low"]
    action: Statement
    rationale: Statement
    evidence: Evidence

    @field_validator("evidence")
    @classmethod
    def _evidence_exists(cls, value: list[str], info: ValidationInfo) -> list[str]:
        return _check_evidence(value, info)


Findings = Annotated[list[Finding], Field(max_length=8)]
Limitation = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]


class AiShiftReport(_Strict):
    executive_summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1500)
    ]
    production_performance: Findings
    quality_observations: Findings
    downtime_maintenance_observations: Findings
    recommendations: Annotated[list[Recommendation], Field(max_length=6)]
    data_limitations: Annotated[list[Limitation], Field(max_length=10)]

    @field_validator("recommendations")
    @classmethod
    def _sorted_by_priority(cls, value: list[Recommendation]) -> list[Recommendation]:
        rank = {"high": 0, "medium": 1, "low": 2}
        return sorted(value, key=lambda r: rank[r.priority])


# --------------------------------------------------------------------------- persisted reports


class ShiftReportSummary(ReadModel):
    id: int
    production_date: date
    shift: str
    window_start: datetime | None
    window_end: datetime | None
    data_source: DataSource | None
    status: ReportStatus
    provider: str | None
    model: str | None
    prompt_version: str
    error_code: str | None
    error_message: str | None
    includes_synthetic_data: bool
    created_at: datetime
    completed_at: datetime | None


class ShiftReportRead(ShiftReportSummary):
    input_fingerprint: str = Field(description="SHA-256 of the metrics snapshot and request")
    metrics: ShiftMetrics
    content: AiShiftReport | None