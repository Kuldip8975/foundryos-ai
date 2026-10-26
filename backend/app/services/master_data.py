"""Machines, products and defect categories (shared logic: same shape, different key)."""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.enums import DataSource
from app.models.manufacturing import DefectCategory, Machine, Product
from app.services.common import apply_changes, commit, get_or_404, paginate

MasterT = TypeVar("MasterT", Machine, Product, DefectCategory)

LABELS: dict[type, str] = {
    Machine: "Machine",
    Product: "Product",
    DefectCategory: "Defect category",
}


def create(db: Session, model: type[MasterT], data: dict[str, Any]) -> MasterT:
    entity = model(**data, data_source=DataSource.MANUAL.value)
    db.add(entity)
    key = model.business_key
    commit(db, conflict_message=f"A {LABELS[model].lower()} with this {key} already exists")
    db.refresh(entity)
    return entity


def get(db: Session, model: type[MasterT], entity_id: int) -> MasterT:
    return get_or_404(db, model, entity_id, LABELS[model])


def list_(
    db: Session,
    model: type[MasterT],
    *,
    is_active: bool | None,
    search: str | None,
    data_source: DataSource | None,
    limit: int,
    offset: int,
    only_ids: frozenset[int] | None = None,
) -> tuple[list[MasterT], int]:
    stmt = select(model)
    if only_ids is not None:  # data scope (an operator's assigned machines)
        stmt = stmt.where(model.id.in_(sorted(only_ids)))
    if is_active is not None:
        stmt = stmt.where(model.is_active == is_active)
    if data_source is not None:
        stmt = stmt.where(model.data_source == data_source.value)
    if search:
        key_column = getattr(model, model.business_key)
        stmt = stmt.where(
            or_(
                key_column.icontains(search, autoescape=True),
                model.name.icontains(search, autoescape=True),
            )
        )
    return paginate(db, stmt, order_by=(model.id,), limit=limit, offset=offset)


def update(db: Session, model: type[MasterT], entity_id: int, changes: dict[str, Any]) -> MasterT:
    entity = get(db, model, entity_id)
    if changes:
        apply_changes(entity, changes)
        commit(db, conflict_message=f"The {LABELS[model].lower()} could not be updated")
        db.refresh(entity)
    return entity