"""Request/response schemas for sign-in and account administration (Module 5).

Passwords appear only in requests. No response ever contains a password
hash or a session token hash; a session token is returned once, at sign-in,
and a temporary password once, when an admin creates an account or resets a
password.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, computed_field

from app.core.passwords import MAX_LENGTH
from app.models.enums import UserRole
from app.schemas.common import EntityId, InputModel, Name, PatchModel, ReadModel

Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=50,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]
# Not stripped: spaces are significant in a password. Length is bounded so a
# huge input cannot make hashing expensive.
Password = Annotated[str, Field(min_length=1, max_length=MAX_LENGTH)]
MachineIds = Annotated[list[EntityId], Field(max_length=200)]


# --------------------------------------------------------------------------- sign-in


class LoginRequest(InputModel):
    username: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=254)
    ] = Field(description="Username or work email")
    password: Password


class MachineRef(ReadModel):
    id: int
    code: str
    name: str
    is_active: bool


class CurrentUser(BaseModel):
    id: int
    username: str
    display_name: str
    email: str | None
    role: UserRole
    permissions: list[str]
    must_change_password: bool
    home: str = Field(description="Page the web client opens after sign-in")
    machine_scope: Literal["assigned", "all"]
    machines: list[MachineRef] = Field(description="Assigned machines (operators only)")
    session_expires_at: datetime | None
    idle_timeout_minutes: int


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - a scheme name, not a secret
    expires_at: datetime
    user: CurrentUser


class PasswordChange(InputModel):
    current_password: Password
    new_password: Password


# --------------------------------------------------------------------------- admin


class UserCreate(InputModel):
    username: Username
    display_name: Name
    email: Email | None = None
    role: UserRole
    machine_ids: MachineIds = Field(default_factory=list)
    temporary_password: Password | None = Field(
        default=None,
        description="A password the admin chooses. Leave empty to have the server generate one.",
    )
    require_password_change: bool = Field(
        default=True,
        description="Ask the person to choose their own password at first sign-in. "
        "Always true for a generated password.",
    )


class PasswordReset(InputModel):
    """Admin password reset. Without new_password the server generates one."""

    new_password: Password | None = None
    require_password_change: bool = True


class UserUpdate(PatchModel):
    """The username is permanent; everything else an admin may change."""

    non_nullable_fields = frozenset({"display_name", "role", "machine_ids"})

    display_name: Name | None = None
    email: Email | None = None
    role: UserRole | None = None
    machine_ids: MachineIds | None = None


class UserStatusChange(InputModel):
    is_active: bool


class UserRead(ReadModel):
    id: int
    username: str
    display_name: str
    email: str | None
    role: UserRole
    is_active: bool
    must_change_password: bool
    locked_until: datetime | None
    last_login_at: datetime | None
    password_changed_at: datetime | None
    deactivated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    machine_ids: list[int]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > datetime.now(
            self.locked_until.tzinfo
        )


class UserWithPassword(BaseModel):
    """Returned once when an account is created or its password is reset."""

    user: UserRead
    temporary_password: str | None = Field(
        description="Shown once when the server generated it (null when the admin chose it). "
        "The person must change a generated password at first sign-in."
    )


class AuditEventRead(ReadModel):
    id: int
    event_type: str
    actor_username: str | None
    target_username: str | None
    target_user_id: int | None
    success: bool
    details: dict[str, Any]
    created_at: datetime