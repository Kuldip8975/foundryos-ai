"""Machines, products and defect categories.

This module intentionally does not use ``from __future__ import annotations``:
the router factory annotates handlers with schema classes passed in as
arguments, which FastAPI must be able to resolve at definition time.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from app.api.auth import require
from app.api.deps import DbSession, EntityPathId, PageParams
from app.api.routes.responses import ERROR_RESPONSES
from app.core.errors import NotFoundError
from app.core.permissions import Permission
from app.models.enums import DataSource
from app.models.manufacturing import DefectCategory, Machine, Product
from app.schemas.common import Page
from app.schemas.manufacturing import (
    DefectCategoryCreate,
    DefectCategoryRead,
    DefectCategoryUpdate,
    MachineCreate,
    MachineRead,
    MachineUpdate,
    ProductCreate,
    ProductRead,
    ProductUpdate,
)
from app.services import master_data
from app.services.auth.sessions import Principal

Reader = Annotated[Principal, Depends(require(Permission.MACHINES_READ))]
Manager = Annotated[Principal, Depends(require(Permission.MASTER_DATA_MANAGE))]


def _build_router(
    *,
    prefix: str,
    tag: str,
    model: Any,
    create_schema: type[BaseModel],
    update_schema: type[BaseModel],
    read_schema: type[BaseModel],
    noun: str,
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag], responses=ERROR_RESPONSES)

    @router.post(
        "", response_model=read_schema, status_code=status.HTTP_201_CREATED,
        summary=f"Create a {noun}",
    )
    def create(payload: create_schema, db: DbSession, _: Manager) -> Any:
        return master_data.create(db, model, payload.values())

    @router.get("", response_model=Page[read_schema], summary=f"List {noun}s")
    def list_(
        db: DbSession,
        principal: Reader,
        page: PageParams,
        is_active: Annotated[bool | None, Query()] = None,
        q: Annotated[
            str | None,
            Query(min_length=1, max_length=100, description="Search code/part number and name"),
        ] = None,
        data_source: Annotated[DataSource | None, Query()] = None,
    ) -> Any:
        items, total = master_data.list_(
            db, model, is_active=is_active, search=q, data_source=data_source,
            limit=page.limit, offset=page.offset,
            only_ids=principal.machine_ids if model is Machine else None,
        )
        return Page[read_schema](
            items=[read_schema.model_validate(i) for i in items],
            total=total, limit=page.limit, offset=page.offset,
        )

    @router.get("/{entity_id}", response_model=read_schema, summary=f"Get a {noun}")
    def get(entity_id: EntityPathId, db: DbSession, principal: Reader) -> Any:
        if model is Machine and not principal.machine_allowed(entity_id):
            # Same answer as a missing machine: ids outside the scope are not disclosed.
            raise NotFoundError(f"Machine {entity_id} was not found")
        return master_data.get(db, model, entity_id)

    @router.patch("/{entity_id}", response_model=read_schema, summary=f"Update a {noun}")
    def update(
        entity_id: EntityPathId, payload: update_schema, db: DbSession, _: Manager
    ) -> Any:
        return master_data.update(db, model, entity_id, payload.changes())

    return router


machines_router = _build_router(
    prefix="/machines", tag="machines", model=Machine, noun="machine",
    create_schema=MachineCreate, update_schema=MachineUpdate, read_schema=MachineRead,
)
products_router = _build_router(
    prefix="/products", tag="products", model=Product, noun="product",
    create_schema=ProductCreate, update_schema=ProductUpdate, read_schema=ProductRead,
)
defect_categories_router = _build_router(
    prefix="/defect-categories", tag="defect categories", model=DefectCategory,
    noun="defect category",
    create_schema=DefectCategoryCreate, update_schema=DefectCategoryUpdate,
    read_schema=DefectCategoryRead,
)