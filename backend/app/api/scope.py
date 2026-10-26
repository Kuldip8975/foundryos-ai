"""Data-scope checks shared by the manufacturing routes (Module 5).

Operators work only with their assigned machines:
* reading a record on another machine answers 404, exactly like a missing
  record, so ids outside the scope are not disclosed;
* recording data for another machine answers 403 ``machine_not_assigned``.
Roles without a machine scope (``Principal.machine_ids is None``) pass.
"""

from __future__ import annotations

from app.core.errors import BusinessRuleError, ForbiddenError, NotFoundError
from app.services.auth.sessions import Principal


def ensure_visible(
    principal: Principal, machine_id: int | None, label: str, entity_id: int
) -> None:
    if not principal.machine_allowed(machine_id):
        raise NotFoundError(f"{label} {entity_id} was not found")


def ensure_assigned(
    principal: Principal, machine_id: int | None, *, field: str = "machine_id"
) -> None:
    if principal.machine_ids is None:
        return
    if machine_id is None:
        raise BusinessRuleError(
            "Choose one of the machines assigned to you.",
            code="machine_required",
            details=[{"field": field}],
        )
    if machine_id not in principal.machine_ids:
        raise ForbiddenError(
            f"Machine {machine_id} is not assigned to you.",
            code="machine_not_assigned",
            details=[{"field": field}],
        )