"""Dashboard analytics (read-only; thin HTTP layer over app.services.analytics)."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.auth import require
from app.api.deps import DbSession, EntityQueryId
from app.api.routes.responses import ERROR_RESPONSES
from app.core.permissions import Permission
from app.models.enums import DataSource
from app.schemas.analytics import DashboardSummary
from app.services import analytics as service

# Plant-wide figures: supervisors and production managers (not machine-scoped operators).
analytics_router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    responses=ERROR_RESPONSES,
    dependencies=[Depends(require(Permission.ANALYTICS_READ))],
)

# UTC offsets in use worldwide range from -12:00 to +14:00.
MIN_UTC_OFFSET_MINUTES = -12 * 60
MAX_UTC_OFFSET_MINUTES = 14 * 60


@analytics_router.get(
    "/dashboard",
    response_model=DashboardSummary,
    summary="Dashboard KPIs, trends, downtime and maintenance summaries",
)
def get_dashboard_summary(
    db: DbSession,
    date_from: Annotated[
        date | None, Query(description="Plant calendar date, inclusive (production_date >=)")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Plant calendar date, inclusive (production_date <=)")
    ] = None,
    shift: Annotated[
        str | None, Query(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9_-]+$")
    ] = None,
    machine_id: EntityQueryId = None,
    product_id: EntityQueryId = None,
    data_source: Annotated[DataSource | None, Query()] = None,
    utc_offset_minutes: Annotated[
        int,
        Query(
            ge=MIN_UTC_OFFSET_MINUTES,
            le=MAX_UTC_OFFSET_MINUTES,
            description="Plant UTC offset used to turn the date range into a UTC window "
            "for downtime and maintenance (e.g. 330 for UTC+05:30).",
        ),
    ] = 0,
) -> Any:
    filters = service.DashboardFilters(
        date_from=date_from, date_to=date_to, shift=shift, machine_id=machine_id,
        product_id=product_id, data_source=data_source, utc_offset_minutes=utc_offset_minutes,
    )
    return service.dashboard_summary(db, filters)