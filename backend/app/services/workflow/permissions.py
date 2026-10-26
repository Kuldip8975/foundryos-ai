"""Role → permission mapping for the workflow assistant (Module 4).

Fixed in code and checked by the backend on every request and every tool
call. The language model is never asked whether something is allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.errors import ForbiddenError
from app.models.enums import WorkflowRole


class Permission(StrEnum):
    RUN_WORKFLOW = "workflow:run"
    READ_DATA = "data:read"
    PROPOSE_MAINTENANCE = "maintenance:propose"
    DECIDE_ACTIONS = "actions:decide"
    VIEW_ALL_SESSIONS = "workflow:view_all"


ROLE_PERMISSIONS: dict[WorkflowRole, frozenset[Permission]] = {
    WorkflowRole.VIEWER: frozenset({Permission.RUN_WORKFLOW, Permission.READ_DATA}),
    WorkflowRole.OPERATOR: frozenset(
        {Permission.RUN_WORKFLOW, Permission.READ_DATA, Permission.PROPOSE_MAINTENANCE}
    ),
    WorkflowRole.SUPERVISOR: frozenset(Permission),
}


@dataclass(frozen=True)
class Actor:
    """The authenticated person making a request.

    ``machine_codes`` limits the assistant's data tools to those machines
    (operators signed in with an account, Module 5); None means no limit.
    """

    name: str
    role: WorkflowRole
    machine_codes: frozenset[str] | None = None

    @property
    def permissions(self) -> frozenset[Permission]:
        return ROLE_PERMISSIONS[self.role]

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions


__all__ = ["ROLE_PERMISSIONS", "Actor", "ForbiddenError", "Permission", "require"]


def require(actor: Actor, permission: Permission) -> None:
    if not actor.can(permission):
        raise ForbiddenError(
            f"Your role ({actor.role.value}) does not allow this action.",
            details=[{"permission": permission.value}],
        )