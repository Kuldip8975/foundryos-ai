"""Helpers shared by the manufacturing services.

Services own transactions: each mutating function validates, applies the
change and commits once. A failed commit is rolled back and reported as a
generic conflict — database driver messages never reach API clients.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.db.base import Base

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=Base)

# Allowance for clock differences between client devices and the server.
CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)


def get_or_404(db: Session, model: type[ModelT], entity_id: int, label: str) -> ModelT:
    entity = db.get(model, entity_id)
    if entity is None:
        raise NotFoundError(f"{label} {entity_id} was not found")
    return entity


def require_reference(
    db: Session,
    model: type[ModelT],
    entity_id: int,
    *,
    field: str,
    label: str,
    must_be_active: bool = False,
) -> ModelT:
    """Resolve a referenced row or fail with 422 ``invalid_reference``."""
    entity = db.get(model, entity_id)
    if entity is None:
        raise BusinessRuleError(
            f"{label} {entity_id} does not exist",
            code="invalid_reference",
            details=[{"field": field}],
        )
    if must_be_active and not getattr(entity, "is_active", True):
        raise BusinessRuleError(
            f"{label} {entity_id} is inactive and cannot be used for new records",
            code="inactive_reference",
            details=[{"field": field}],
        )
    return entity


def validate_range(
    start: date | datetime | None,
    end: date | datetime | None,
    *,
    start_field: str,
    end_field: str,
    allow_equal: bool = True,
) -> None:
    if start is None or end is None:
        return
    if start > end or (not allow_equal and start == end):
        relation = "on or before" if allow_equal else "before"
        raise BusinessRuleError(
            f"{start_field} must be {relation} {end_field}",
            code="invalid_date_range",
            details=[{"field": start_field}, {"field": end_field}],
        )


def ensure_not_future(value: datetime, *, field: str) -> None:
    if value > datetime.now(UTC) + CLOCK_SKEW_TOLERANCE:
        raise BusinessRuleError(
            f"{field} cannot be in the future", code="future_timestamp", details=[{"field": field}]
        )


def ensure_date_not_future(value: date, *, field: str) -> None:
    # Plants may be ahead of UTC, so "today" can be tomorrow in UTC terms.
    if value > datetime.now(UTC).date() + timedelta(days=1):
        raise BusinessRuleError(
            f"{field} cannot be in the future", code="future_date", details=[{"field": field}]
        )


def paginate(
    db: Session, stmt: Select[Any], *, order_by: tuple[Any, ...], limit: int, offset: int
) -> tuple[list[Any], int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = list(db.scalars(stmt.order_by(*order_by).limit(limit).offset(offset)))
    return items, total


def commit(db: Session, *, conflict_message: str) -> None:
    """Commit the unit of work; map constraint violations to a safe 409."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.info("integrity error on commit", extra={"error_type": type(exc.orig).__name__})
        raise ConflictError(conflict_message) from None


def apply_changes(entity: Base, changes: dict[str, Any]) -> None:
    for key, value in changes.items():
        setattr(entity, key, value)