"""Authentication and authorisation dependencies (Module 5).

Every protected endpoint declares the permission it needs:

    def handler(principal: Annotated[Principal, Depends(require(Permission.X))]): ...

``require`` resolves the signed-in person from the bearer token (never from
anything else the client sends), refuses accounts that must change their
password first, and checks the role's permission. Data scope (an operator's
assigned machines) is applied by the handlers through ``Principal``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from app.api.deps import DbSession, get_app_settings
from app.core.config import Settings
from app.core.errors import AuthenticationError, ForbiddenError
from app.core.permissions import Permission
from app.services.auth.rate_limit import SlidingWindowLimiter
from app.services.auth.sessions import Principal, authenticate, principal_for

MAX_AUTH_HEADER = 300


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header[:MAX_AUTH_HEADER].partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def principal_from_token(db: DbSession, settings: Settings, token: str | None) -> Principal:
    if token is None:
        raise AuthenticationError()
    user, session = authenticate(db, settings, token)
    return principal_for(user, session)


def get_account_principal(
    request: Request,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> Principal:
    """The signed-in person, even if they must still change their password."""
    return principal_from_token(db, settings, bearer_token(request))


def get_principal(
    principal: Annotated[Principal, Depends(get_account_principal)],
) -> Principal:
    """The signed-in person, cleared for normal work."""
    if principal.must_change_password:
        raise ForbiddenError(
            "Change your temporary password before continuing.",
            code="password_change_required",
        )
    return principal


def require(permission: Permission) -> Callable[[Principal], Principal]:
    def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        principal.require(permission)
        return principal

    dependency.__name__ = f"require_{permission.name.lower()}"
    return dependency


def get_login_limiter(request: Request) -> SlidingWindowLimiter:
    return request.app.state.login_limiter


def client_address(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


AccountPrincipal = Annotated[Principal, Depends(get_account_principal)]
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
LoginLimiter = Annotated[SlidingWindowLimiter, Depends(get_login_limiter)]