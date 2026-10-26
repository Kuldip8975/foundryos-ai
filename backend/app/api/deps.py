"""Shared FastAPI dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_db

MAX_PAGE_SIZE = 200
MAX_ID = 9_223_372_036_854_775_807  # PostgreSQL BIGINT
DEFAULT_PAGE_SIZE = 50


def get_app_settings(request: Request) -> Settings:
    """Settings the running application was created with (see ``create_app``)."""
    return request.app.state.settings


DbSession = Annotated[Session, Depends(get_db)]


@dataclass(frozen=True)
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="Page size")] = (
        DEFAULT_PAGE_SIZE
    ),
    offset: Annotated[int, Query(ge=0, le=1_000_000, description="Rows to skip")] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


PageParams = Annotated[Pagination, Depends(pagination)]

# Identifiers in paths and filters: positive and within BIGINT, so out-of-range
# values are a clean 422 instead of a database error.
EntityPathId = Annotated[int, Path(gt=0, le=MAX_ID)]
EntityQueryId = Annotated[int | None, Query(gt=0, le=MAX_ID)]