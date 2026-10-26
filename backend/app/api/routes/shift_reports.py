"""Shift analysis and AI shift reports (thin HTTP layer over app.services)."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import AwareDatetime, ValidationError

from app.api.auth import require
from app.api.deps import DbSession, EntityPathId, PageParams, get_app_settings
from app.api.routes.responses import ERROR_RESPONSES
from app.core.config import Settings
from app.core.permissions import Permission
from app.models.enums import DataSource, ReportStatus
from app.schemas.common import Page
from app.schemas.errors import ErrorResponse
from app.schemas.shift_reports import (
    ShiftMetrics,
    ShiftReportCreate,
    ShiftReportRead,
    ShiftReportSummary,
    ShiftScopeIn,
)
from app.services import shift_reports as service
from app.services.ai_provider import GeminiProvider, ReportProvider

AI_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **ERROR_RESPONSES,
    429: {"model": ErrorResponse, "description": "AI provider rate limit"},
    502: {"model": ErrorResponse, "description": "AI provider error or invalid AI output"},
    503: {"model": ErrorResponse, "description": "AI reports are not configured"},
    504: {"model": ErrorResponse, "description": "AI provider timeout"},
}

analysis_router = APIRouter(
    prefix="/shift-analysis",
    tags=["shift reports"],
    responses=ERROR_RESPONSES,
    dependencies=[Depends(require(Permission.ANALYTICS_READ))],
)
reports_router = APIRouter(
    prefix="/shift-reports",
    tags=["shift reports"],
    responses=AI_ERROR_RESPONSES,
    dependencies=[Depends(require(Permission.REPORTS_READ))],
)

ShiftCode = Annotated[str, Query(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9_-]+$")]
OptionalShiftCode = Annotated[
    str | None, Query(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9_-]+$")
]


def get_report_provider(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ReportProvider | None:
    """The configured provider, or None when AI reports are disabled / have no key."""
    if not settings.ai_configured or settings.gemini_api_key is None:
        return None
    return GeminiProvider(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_model,
        timeout_seconds=settings.ai_request_timeout_seconds,
        thinking_level=settings.gemini_thinking_level or None,
    )


def shift_scope_query(
    production_date: Annotated[date, Query(description="Plant calendar date")],
    shift: ShiftCode,
    window_start: Annotated[AwareDatetime | None, Query(description="UTC offset required")] = None,
    window_end: Annotated[AwareDatetime | None, Query(description="UTC offset required")] = None,
    data_source: Annotated[DataSource | None, Query()] = None,
) -> ShiftScopeIn:
    try:
        return ShiftScopeIn(
            production_date=production_date, shift=shift, window_start=window_start,
            window_end=window_end, data_source=data_source,
        )
    except ValidationError as exc:  # cross-field rules → standard 422 envelope
        raise RequestValidationError(exc.errors()) from None


@analysis_router.get(
    "", response_model=ShiftMetrics, summary="Deterministic metrics for one shift (no AI)"
)
def get_shift_analysis(
    db: DbSession, scope: Annotated[ShiftScopeIn, Depends(shift_scope_query)]
) -> Any:
    return service.analyse_shift(db, scope)


@reports_router.post(
    "",
    response_model=ShiftReportRead,
    status_code=status.HTTP_201_CREATED,
    summary="Generate an AI shift report (200 if identical data already has a report)",
    dependencies=[Depends(require(Permission.REPORTS_GENERATE))],
)
def create_shift_report(
    payload: ShiftReportCreate,
    db: DbSession,
    response: Response,
    provider: Annotated[ReportProvider | None, Depends(get_report_provider)],
) -> Any:
    result = service.generate_shift_report(
        db, payload, provider=provider, regenerate=payload.regenerate
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return result.report


@reports_router.get("", response_model=Page[ShiftReportSummary])
def list_shift_reports(
    db: DbSession,
    page: PageParams,
    date_from: Annotated[date | None, Query(description="production_date >= (inclusive)")] = None,
    date_to: Annotated[date | None, Query(description="production_date <= (inclusive)")] = None,
    shift: OptionalShiftCode = None,
    status_: Annotated[ReportStatus | None, Query(alias="status")] = None,
) -> Any:
    filters = service.ReportFilters(
        date_from=date_from, date_to=date_to, shift=shift, status=status_
    )
    items, total = service.list_reports(db, filters, limit=page.limit, offset=page.offset)
    return Page[ShiftReportSummary](
        items=[ShiftReportSummary.model_validate(item) for item in items],
        total=total, limit=page.limit, offset=page.offset,
    )


@reports_router.get("/{report_id}", response_model=ShiftReportRead)
def get_shift_report(report_id: EntityPathId, db: DbSession) -> Any:
    return service.get_report(db, report_id)