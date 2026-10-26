"""Health endpoints.

* ``GET /health/live``  — liveness: the process is up. Never touches the DB, so
  orchestrators don't restart the API just because the database blipped.
* ``GET /health/ready`` — readiness: the DB answers and migrations are at head.
  Returns 200 when ready, 503 (same body shape) when not.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import Engine

from app.api.deps import get_app_settings
from app.core.config import Settings
from app.db.session import get_engine
from app.schemas.health import LivenessResponse, ReadinessResponse
from app.services.health import check_readiness, expected_migration_heads

router = APIRouter(prefix="/health", tags=["health"])


def engine_dependency() -> Engine:
    return get_engine()


def migration_heads_dependency() -> frozenset[str]:
    return expected_migration_heads()


@router.get("/live", response_model=LivenessResponse, summary="Liveness probe")
def liveness(settings: Annotated[Settings, Depends(get_app_settings)]) -> LivenessResponse:
    return LivenessResponse(
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe (database + migrations)",
    responses={503: {"model": ReadinessResponse, "description": "Not ready"}},
)
def readiness(
    response: Response,
    engine: Annotated[Engine, Depends(engine_dependency)],
    heads: Annotated[frozenset[str], Depends(migration_heads_dependency)],
) -> ReadinessResponse:
    result = check_readiness(engine, heads)
    if result.status != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
