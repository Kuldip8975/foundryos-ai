"""Account administration and access audit (Module 5). Admins only."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.api.auth import require
from app.api.deps import DbSession, EntityPathId, EntityQueryId, PageParams, get_app_settings
from app.api.routes.auth import AUTH_RESPONSES
from app.core.config import Settings
from app.core.permissions import Permission
from app.models.auth import User
from app.models.enums import UserRole
from app.schemas.auth import (
    AuditEventRead,
    PasswordReset,
    UserCreate,
    UserRead,
    UserStatusChange,
    UserUpdate,
    UserWithPassword,
)
from app.schemas.common import Page
from app.services.auth import users as service
from app.services.auth.sessions import Principal

router = APIRouter(prefix="/admin", tags=["administration"], responses=AUTH_RESPONSES)

UserAdmin = Annotated[Principal, Depends(require(Permission.USERS_MANAGE))]
AuditReader = Annotated[Principal, Depends(require(Permission.AUDIT_READ))]


def _admin_user(db: DbSession, principal: Principal) -> User:
    return service.get_user(db, principal.user_id)


@router.get("/users", response_model=Page[UserRead], summary="List accounts")
def list_users(
    db: DbSession,
    _: UserAdmin,
    page: PageParams,
    role: Annotated[UserRole | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
) -> Any:
    items, total = service.list_users(
        db,
        service.UserFilters(role=role, is_active=is_active, search=q),
        limit=page.limit,
        offset=page.offset,
    )
    return Page[UserRead](
        items=[UserRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/users",
    response_model=UserWithPassword,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account with a one-time password",
)
def create_user(
    payload: UserCreate,
    db: DbSession,
    principal: UserAdmin,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> Any:
    user, password = service.create_user(db, settings, _admin_user(db, principal), payload.values())
    return UserWithPassword(user=UserRead.model_validate(user), temporary_password=password)


@router.get("/users/{user_id}", response_model=UserRead, summary="One account")
def get_user(user_id: EntityPathId, db: DbSession, _: UserAdmin) -> Any:
    return UserRead.model_validate(service.get_user(db, user_id))


@router.patch(
    "/users/{user_id}",
    response_model=UserRead,
    summary="Change name, email, role or assigned machines",
)
def update_user(
    user_id: EntityPathId, payload: UserUpdate, db: DbSession, principal: UserAdmin
) -> Any:
    user = service.update_user(db, _admin_user(db, principal), user_id, payload.changes())
    return UserRead.model_validate(user)


@router.post(
    "/users/{user_id}/status",
    response_model=UserRead,
    summary="Deactivate (ends every session) or reactivate an account",
)
def set_status(
    user_id: EntityPathId, payload: UserStatusChange, db: DbSession, principal: UserAdmin
) -> Any:
    user = service.set_active(db, _admin_user(db, principal), user_id, payload.is_active)
    return UserRead.model_validate(user)


@router.post(
    "/users/{user_id}/reset-password",
    response_model=UserWithPassword,
    summary="Set a new password (chosen by the admin or generated) and end every session",
)
def reset_password(
    user_id: EntityPathId,
    db: DbSession,
    principal: UserAdmin,
    payload: PasswordReset | None = None,
) -> Any:
    payload = payload or PasswordReset()
    user, password = service.reset_password(
        db,
        _admin_user(db, principal),
        user_id,
        new_password=payload.new_password,
        require_password_change=payload.require_password_change,
    )
    return UserWithPassword(user=UserRead.model_validate(user), temporary_password=password)


@router.get("/audit-events", response_model=Page[AuditEventRead], summary="Access audit log")
def list_audit_events(
    db: DbSession,
    _: AuditReader,
    page: PageParams,
    event_type: Annotated[
        str | None, Query(min_length=1, max_length=50, pattern=r"^[a-z_]+$")
    ] = None,
    user_id: EntityQueryId = None,
    success: Annotated[bool | None, Query()] = None,
) -> Any:
    items, total = service.list_audit_events(
        db,
        service.AuditFilters(event_type=event_type, user_id=user_id, success=success),
        limit=page.limit,
        offset=page.offset,
    )
    return Page[AuditEventRead](
        items=[AuditEventRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )