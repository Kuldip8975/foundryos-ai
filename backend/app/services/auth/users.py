"""Account administration (Module 5). Admins only; checked by the API layer.

Safeguards:
* admins cannot deactivate or demote themselves, and the last active admin
  can never be deactivated or demoted, so the system cannot be locked out;
* a deactivated account's sessions end immediately;
* a password reset sets a one-time password, ends every session and forces a
  password change at the next sign-in;
* machine assignments exist only for operators (other roles see the whole
  plant or no manufacturing data at all);
* usernames are permanent and must not collide with a legacy Module 4
  workflow-token name, so workflow history stays unambiguous.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from app.core.passwords import generate_temporary_password, hash_password, password_problem
from app.core.permissions import MACHINE_SCOPED_ROLES
from app.models.auth import AuthAuditEvent, User, UserMachineAssignment
from app.models.enums import UserRole
from app.models.manufacturing import Machine
from app.services.auth.audit import record_auth_event
from app.services.auth.sessions import revoke_user_sessions
from app.services.common import paginate


@dataclass(frozen=True)
class UserFilters:
    role: UserRole | None = None
    is_active: bool | None = None
    search: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} was not found")
    return user


def list_users(
    db: Session, filters: UserFilters, *, limit: int, offset: int
) -> tuple[list[User], int]:
    stmt = select(User)
    if filters.role is not None:
        stmt = stmt.where(User.role == filters.role.value)
    if filters.is_active is not None:
        stmt = stmt.where(User.is_active == filters.is_active)
    if filters.search:
        stmt = stmt.where(
            or_(
                User.username.icontains(filters.search, autoescape=True),
                User.display_name.icontains(filters.search, autoescape=True),
                User.email.icontains(filters.search, autoescape=True),
            )
        )
    return paginate(db, stmt, order_by=(User.username,), limit=limit, offset=offset)


def active_admin_count(db: Session) -> int:
    return db.scalar(
        select(func.count(User.id)).where(
            User.role == UserRole.ADMIN.value, User.is_active.is_(True)
        )
    ) or 0


# --------------------------------------------------------------------------- validation


def _check_password(password: str, username: str) -> None:
    problem = password_problem(password, username=username)
    if problem is not None:
        raise BusinessRuleError(
            problem, code="weak_password", details=[{"field": "temporary_password"}]
        )


def _check_legacy_name(settings: Settings, username: str) -> None:
    if any(entry.name.lower() == username for entry in settings.workflow_access_entries):
        raise ConflictError(
            "This username is already used by a workflow access token. Choose another.",
            code="username_taken",
            details=[{"field": "username"}],
        )


def _check_unique(
    db: Session, *, username: str | None, email: str | None, user_id: int | None
) -> None:
    if username is not None:
        clash = db.scalar(select(User.id).where(User.username == username))
        if clash is not None and clash != user_id:
            raise ConflictError(
                "This username is already taken.",
                code="username_taken",
                details=[{"field": "username"}],
            )
    if email is not None:
        clash = db.scalar(select(User.id).where(User.email == email))
        if clash is not None and clash != user_id:
            raise ConflictError(
                "Another account already uses this email.",
                code="email_taken",
                details=[{"field": "email"}],
            )


def _resolve_machines(db: Session, role: UserRole, machine_ids: Iterable[int]) -> list[int]:
    ids = sorted(set(machine_ids))
    if ids and role not in MACHINE_SCOPED_ROLES:
        raise BusinessRuleError(
            "Machines can only be assigned to operators; other roles see the whole plant "
            "or no manufacturing data.",
            code="machines_not_applicable",
            details=[{"field": "machine_ids"}],
        )
    if ids:
        found = set(db.scalars(select(Machine.id).where(Machine.id.in_(ids))))
        missing = [machine_id for machine_id in ids if machine_id not in found]
        if missing:
            raise BusinessRuleError(
                f"These machines do not exist: {', '.join(map(str, missing))}",
                code="invalid_reference",
                details=[{"field": "machine_ids"}],
            )
    return ids


def _set_machines(user: User, machine_ids: list[int]) -> None:
    wanted = set(machine_ids)
    user.machine_assignments[:] = [
        assignment for assignment in user.machine_assignments if assignment.machine_id in wanted
    ]
    have = {assignment.machine_id for assignment in user.machine_assignments}
    for machine_id in sorted(wanted - have):
        user.machine_assignments.append(UserMachineAssignment(machine_id=machine_id))


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError(
            "The account could not be saved because of a conflicting change. Try again.",
            code="conflict",
        ) from None


# --------------------------------------------------------------------------- changes


def create_user(
    db: Session,
    settings: Settings,
    admin: User | None,
    data: dict[str, Any],
    *,
    event_type: str = "user_created",
) -> tuple[User, str | None]:
    """Create an account. Returns the user and the generated password (if one was generated)."""
    role = UserRole(data["role"])
    username = data["username"]
    email = data.get("email")
    _check_legacy_name(settings, username)
    _check_unique(db, username=username, email=email, user_id=None)
    machine_ids = _resolve_machines(db, role, data.get("machine_ids") or [])
    supplied = data.get("temporary_password")
    if supplied is not None:
        _check_password(supplied, username)
    password = supplied if supplied is not None else generate_temporary_password()

    user = User(
        username=username,
        email=email,
        display_name=data["display_name"],
        role=role.value,
        password_hash=hash_password(password),
        is_active=True,
        # A generated password must always be replaced; an admin-chosen one only if asked.
        must_change_password=supplied is None or bool(data.get("require_password_change", True)),
        created_by_id=admin.id if admin is not None else None,
    )
    _set_machines(user, machine_ids)
    db.add(user)
    db.flush()
    record_auth_event(
        db,
        event_type,
        actor=admin,
        actor_username=None if admin is not None else "command-line",
        target=user,
        details={
            "role": role.value,
            "machine_count": len(machine_ids),
            "password": "chosen_by_admin" if supplied is not None else "generated",
            "must_change_password": user.must_change_password,
        },
    )
    _commit(db)
    db.refresh(user)
    return user, (None if supplied is not None else password)


def update_user(db: Session, admin: User, user_id: int, changes: dict[str, Any]) -> User:
    user = get_user(db, user_id)
    if not changes:
        return user
    new_role = UserRole(changes.get("role", user.role))
    old_role = UserRole(user.role)
    if new_role != old_role:
        if user.id == admin.id:
            raise ForbiddenError(
                "You cannot change your own role. Ask another admin.", code="self_change_forbidden"
            )
        if old_role is UserRole.ADMIN and user.is_active and active_admin_count(db) <= 1:
            raise ConflictError(
                "This is the last active admin; their role cannot be changed.",
                code="last_admin",
            )
    if "email" in changes:
        _check_unique(db, username=None, email=changes["email"], user_id=user.id)

    if "machine_ids" in changes:
        machine_ids = _resolve_machines(db, new_role, changes["machine_ids"])
    elif new_role not in MACHINE_SCOPED_ROLES:
        machine_ids = []  # assignments only make sense for operators
    else:
        machine_ids = user.machine_ids

    changed = sorted(
        field
        for field in ("display_name", "email", "role")
        if field in changes and changes[field] != getattr(user, field)
    )
    before_machines = set(user.machine_ids)
    for field in ("display_name", "email"):
        if field in changes:
            setattr(user, field, changes[field])
    user.role = new_role.value
    _set_machines(user, machine_ids)
    if set(machine_ids) != before_machines:
        changed.append("machine_ids")
    if changed:
        details: dict[str, Any] = {"fields": changed}
        if "role" in changed:
            details.update(role_from=old_role.value, role_to=new_role.value)
        if "machine_ids" in changed:
            details["machine_count"] = len(machine_ids)
        record_auth_event(db, "user_updated", actor=admin, target=user, details=details)
    _commit(db)
    db.refresh(user)
    return user


def set_active(db: Session, admin: User, user_id: int, active: bool) -> User:
    user = get_user(db, user_id)
    if user.is_active == active:
        return user
    now = _now()
    if not active:
        if user.id == admin.id:
            raise ForbiddenError(
                "You cannot deactivate your own account.", code="self_change_forbidden"
            )
        if user.role == UserRole.ADMIN.value and active_admin_count(db) <= 1:
            raise ConflictError(
                "This is the last active admin and cannot be deactivated.", code="last_admin"
            )
        user.is_active = False
        user.deactivated_at = now
        ended = revoke_user_sessions(db, user.id, "deactivated", now=now)
        record_auth_event(
            db, "user_deactivated", actor=admin, target=user, details={"sessions_ended": ended}
        )
    else:
        user.is_active = True
        user.deactivated_at = None
        user.failed_login_count = 0
        user.locked_until = None
        record_auth_event(db, "user_reactivated", actor=admin, target=user, details={})
    _commit(db)
    db.refresh(user)
    return user


def reset_password(
    db: Session,
    admin: User,
    user_id: int,
    *,
    new_password: str | None = None,
    require_password_change: bool = True,
) -> tuple[User, str | None]:
    """Set a new password. Returns the generated password, or None if the admin chose it."""
    user = get_user(db, user_id)
    if user.id == admin.id:
        raise ForbiddenError(
            "Use 'Change password' for your own account.", code="self_change_forbidden"
        )
    now = _now()
    if new_password is not None:
        problem = password_problem(new_password, username=user.username)
        if problem is not None:
            raise BusinessRuleError(
                problem, code="weak_password", details=[{"field": "new_password"}]
            )
    password = new_password if new_password is not None else generate_temporary_password()
    user.password_hash = hash_password(password)
    user.must_change_password = new_password is None or require_password_change
    user.failed_login_count = 0
    user.locked_until = None
    ended = revoke_user_sessions(db, user.id, "password_reset", now=now)
    record_auth_event(
        db,
        "password_reset",
        actor=admin,
        target=user,
        details={
            "sessions_ended": ended,
            "chosen_by_admin": new_password is not None,
            "must_change_password": user.must_change_password,
        },
    )
    _commit(db)
    db.refresh(user)
    return user, (None if new_password is not None else password)


# --------------------------------------------------------------------------- audit


@dataclass(frozen=True)
class AuditFilters:
    event_type: str | None = None
    user_id: int | None = None
    success: bool | None = None


def list_audit_events(
    db: Session, filters: AuditFilters, *, limit: int, offset: int
) -> tuple[list[AuthAuditEvent], int]:
    stmt = select(AuthAuditEvent)
    if filters.event_type is not None:
        stmt = stmt.where(AuthAuditEvent.event_type == filters.event_type)
    if filters.user_id is not None:
        stmt = stmt.where(
            or_(
                AuthAuditEvent.target_user_id == filters.user_id,
                AuthAuditEvent.actor_user_id == filters.user_id,
            )
        )
    if filters.success is not None:
        stmt = stmt.where(AuthAuditEvent.success == filters.success)
    order = (AuthAuditEvent.created_at.desc(), AuthAuditEvent.id.desc())
    return paginate(db, stmt, order_by=order, limit=limit, offset=offset)