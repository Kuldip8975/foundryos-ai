"""Sign-in, sign-out and the signed-in person's own account (Module 5).

There is deliberately no sign-up endpoint: accounts are created by an admin
(``/admin/users``) or, once, by ``python -m app.cli.create_admin``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import AccountPrincipal, LoginLimiter, client_address
from app.api.deps import DbSession, get_app_settings
from app.api.routes.responses import ERROR_RESPONSES
from app.core.config import Settings
from app.core.permissions import HOME_PAGE
from app.models.auth import AuthSession, User
from app.models.manufacturing import Machine
from app.schemas.auth import (
    CurrentUser,
    LoginRequest,
    LoginResponse,
    MachineRef,
    PasswordChange,
)
from app.schemas.errors import ErrorResponse
from app.services.auth import sessions
from app.services.auth.sessions import Principal, principal_for

AUTH_RESPONSES: dict[int | str, dict[str, Any]] = {
    **ERROR_RESPONSES,
    401: {"model": ErrorResponse, "description": "Not signed in, or the session has ended"},
    403: {"model": ErrorResponse, "description": "The role does not allow this"},
    429: {"model": ErrorResponse, "description": "Too many attempts"},
}

router = APIRouter(prefix="/auth", tags=["authentication"], responses=AUTH_RESPONSES)

AppSettings = Annotated[Settings, Depends(get_app_settings)]


def current_user_view(db: Session, settings: Settings, principal: Principal) -> CurrentUser:
    user = db.get(User, principal.user_id)
    assert user is not None  # the session was just validated
    machines: list[Machine] = []
    if principal.machine_ids:
        machines = list(
            db.scalars(
                select(Machine).where(Machine.id.in_(principal.machine_ids)).order_by(Machine.code)
            )
        )
    return CurrentUser(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=principal.role,
        permissions=sorted(permission.value for permission in principal.permissions),
        must_change_password=user.must_change_password,
        home=HOME_PAGE[principal.role],
        machine_scope="all" if principal.machine_ids is None else "assigned",
        machines=[MachineRef.model_validate(machine) for machine in machines],
        session_expires_at=principal.session_expires_at,
        idle_timeout_minutes=settings.auth_idle_timeout_minutes,
    )


@router.post("/login", response_model=LoginResponse, summary="Sign in with username or email")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: AppSettings,
    limiter: LoginLimiter,
) -> Any:
    signed_in = sessions.login(
        db,
        settings,
        limiter,
        identifier=payload.username,
        password=payload.password,
        client_address=client_address(request),
    )
    response.headers["Cache-Control"] = "no-store"
    principal = principal_for(signed_in.user, signed_in.session)
    return LoginResponse(
        access_token=signed_in.token,
        expires_at=signed_in.session.expires_at,
        user=current_user_view(db, settings, principal),
    )


@router.get("/me", response_model=CurrentUser, summary="The signed-in person and their permissions")
def read_me(principal: AccountPrincipal, db: DbSession, settings: AppSettings) -> Any:
    return current_user_view(db, settings, principal)


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End the current session"
)
def logout(principal: AccountPrincipal, db: DbSession) -> Response:
    sessions.logout(db, principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password",
    response_model=CurrentUser,
    summary="Change your own password (required after a temporary password)",
)
def change_password(
    payload: PasswordChange,
    principal: AccountPrincipal,
    db: DbSession,
    settings: AppSettings,
    limiter: LoginLimiter,
) -> Any:
    user = sessions.change_password(
        db,
        settings,
        limiter,
        principal,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    session = db.get(AuthSession, principal.session_id) if principal.session_id else None
    return current_user_view(db, settings, principal_for(user, session))