"""Sign-in, sessions and password changes (Module 5).

A session token is 256 random bits, returned to the browser once at sign-in
and sent back as ``Authorization: Bearer <token>``. Only its SHA-256 is
stored. Every request re-reads the session and the user, so logout,
deactivation, role changes and machine re-assignment take effect at once.

Failed sign-ins all get the same message, whether the username is unknown,
the password is wrong, the account is locked or deactivated; a password is
always checked (against a dummy hash for unknown names) so response times
match too.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import (
    AuthenticationError,
    BusinessRuleError,
    ForbiddenError,
    TooManyRequestsError,
)
from app.core.passwords import (
    dummy_verify,
    hash_password,
    needs_rehash,
    password_problem,
    verify_password,
)
from app.core.permissions import (
    MACHINE_SCOPED_ROLES,
    Permission,
    permissions_for,
)
from app.models.auth import AuthSession, User
from app.models.enums import UserRole
from app.services.auth.audit import record_auth_event
from app.services.auth.rate_limit import SlidingWindowLimiter

logger = logging.getLogger(__name__)

MIN_TOKEN_LENGTH = 32
MAX_TOKEN_LENGTH = 200
MAX_IDENTIFIER_LENGTH = 254
# last_seen_at is written at most this often, not on every request.
TOUCH_INTERVAL = timedelta(seconds=60)
# Ended sessions are deleted this long after they ended (at the user's next sign-in).
SESSION_RETENTION = timedelta(days=30)

# Shared accounts of a public demo deployment (see app.cli.demo_accounts).
DEMO_USERNAMES = frozenset({"demo.operator", "demo.supervisor", "demo.manager"})

SIGN_IN_FAILED = (
    "Sign-in failed. Check your username and password. After several failed attempts "
    "sign-in is paused for a few minutes."
)
TOO_MANY_ATTEMPTS = "Too many sign-in attempts. Wait a few minutes and try again."


@dataclass(frozen=True)
class Principal:
    """The signed-in person behind a request, as established by the server."""

    user_id: int
    username: str
    display_name: str
    role: UserRole
    session_id: int | None
    must_change_password: bool
    # Machines the person may see and record data for; None means every machine.
    machine_ids: frozenset[int] | None
    session_expires_at: datetime | None = None

    @property
    def permissions(self) -> frozenset[Permission]:
        return permissions_for(self.role)

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions

    def require(self, permission: Permission) -> None:
        if not self.can(permission):
            raise ForbiddenError(
                "Your role does not allow this.",
                details=[{"permission": permission.value}],
            )

    def machine_allowed(self, machine_id: int | None) -> bool:
        if self.machine_ids is None:
            return True
        return machine_id is not None and machine_id in self.machine_ids


@dataclass(frozen=True)
class SignIn:
    token: str
    session: AuthSession
    user: User


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_identifier(value: str) -> str:
    return value.strip().lower()


def principal_for(user: User, session: AuthSession | None) -> Principal:
    role = UserRole(user.role)
    return Principal(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=role,
        session_id=session.id if session is not None else None,
        must_change_password=user.must_change_password,
        machine_ids=frozenset(user.machine_ids) if role in MACHINE_SCOPED_ROLES else None,
        session_expires_at=session.expires_at if session is not None else None,
    )


# --------------------------------------------------------------------------- sign-in


def _find_user(db: Session, identifier: str) -> User | None:
    return db.scalar(
        select(User).where(or_(User.username == identifier, User.email == identifier))
    )


def login(
    db: Session,
    settings: Settings,
    limiter: SlidingWindowLimiter,
    *,
    identifier: str,
    password: str,
    client_address: str,
    now: datetime | None = None,
) -> SignIn:
    now = now or datetime.now(UTC)
    identifier = normalize_identifier(identifier)[:MAX_IDENTIFIER_LENGTH]
    keys = (f"ip:{client_address}", f"user:{identifier}")
    if limiter.blocked(*keys):
        logger.warning("sign-in rate limited")
        raise TooManyRequestsError(TOO_MANY_ATTEMPTS, code="too_many_attempts")

    user = _find_user(db, identifier) if identifier else None
    if user is None:
        dummy_verify(password)
        limiter.hit(*keys)
        record_auth_event(
            db, "login_failed", success=False, details={"reason": "unknown_account"}
        )
        db.commit()
        raise AuthenticationError(SIGN_IN_FAILED, code="invalid_credentials")

    password_ok = verify_password(password, user.password_hash)
    locked = user.locked_until is not None and now < user.locked_until
    if locked or not password_ok or not user.is_active:
        limiter.hit(*keys)
        reason = "locked" if locked else ("wrong_password" if not password_ok else "inactive")
        if not password_ok and not locked:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.auth_max_failed_logins:
                user.failed_login_count = 0
                user.locked_until = now + timedelta(minutes=settings.auth_lockout_minutes)
                record_auth_event(
                    db,
                    "account_locked",
                    target=user,
                    success=False,
                    details={"minutes": settings.auth_lockout_minutes},
                )
        record_auth_event(
            db, "login_failed", target=user, success=False, details={"reason": reason}
        )
        db.commit()
        raise AuthenticationError(SIGN_IN_FAILED, code="invalid_credentials")

    # Success.
    limiter.reset(f"user:{identifier}")
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    db.execute(
        delete(AuthSession).where(
            AuthSession.user_id == user.id,
            or_(
                AuthSession.expires_at < now - SESSION_RETENTION,
                AuthSession.revoked_at < now - SESSION_RETENTION,
            ),
        )
    )
    token = secrets.token_urlsafe(32)
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        created_at=now,
        expires_at=now + timedelta(minutes=settings.auth_session_ttl_minutes),
        last_seen_at=now,
    )
    db.add(session)
    db.flush()
    record_auth_event(
        db,
        "login_succeeded",
        actor=user,
        target=user,
        details={"session_id": session.id, "must_change_password": user.must_change_password},
    )
    db.commit()
    db.refresh(user)
    return SignIn(token=token, session=session, user=user)


# --------------------------------------------------------------------------- requests


def authenticate(
    db: Session, settings: Settings, token: str, *, now: datetime | None = None
) -> tuple[User, AuthSession]:
    """The active user and session for ``token``; raises AuthenticationError otherwise."""
    now = now or datetime.now(UTC)
    if not (MIN_TOKEN_LENGTH <= len(token) <= MAX_TOKEN_LENGTH):
        raise AuthenticationError()
    row = db.execute(
        select(AuthSession, User)
        .join(User, AuthSession.user_id == User.id)
        .where(AuthSession.token_hash == hash_session_token(token))
    ).first()
    if row is None:
        raise AuthenticationError()
    session, user = row
    if session.revoked_at is not None:
        if session.revoke_reason in {"expired", "idle_timeout"}:
            raise AuthenticationError(
                "Your session has expired. Sign in again.", code="session_expired"
            )
        raise AuthenticationError(
            "Your session has ended. Sign in again.", code="session_revoked"
        )
    idle_limit = timedelta(minutes=settings.auth_idle_timeout_minutes)
    expired = now >= session.expires_at
    if expired or now - session.last_seen_at >= idle_limit:
        session.revoked_at = now
        session.revoke_reason = "expired" if expired else "idle_timeout"
        record_auth_event(
            db,
            "session_expired",
            actor=user,
            target=user,
            details={"session_id": session.id, "reason": session.revoke_reason},
        )
        db.commit()
        raise AuthenticationError(
            "Your session has expired. Sign in again.", code="session_expired"
        )
    if not user.is_active:
        session.revoked_at = now
        session.revoke_reason = "deactivated"
        db.commit()
        raise AuthenticationError(
            "Your session has ended. Sign in again.", code="session_revoked"
        )
    if now - session.last_seen_at >= TOUCH_INTERVAL:
        session.last_seen_at = now
        db.commit()
    return user, session


def revoke_user_sessions(
    db: Session,
    user_id: int,
    reason: str,
    *,
    now: datetime,
    keep_session_id: int | None = None,
) -> int:
    """Revoke every active session of a user (the caller commits)."""
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason=reason)
        .execution_options(synchronize_session=False)
    )
    if keep_session_id is not None:
        stmt = stmt.where(AuthSession.id != keep_session_id)
    return db.execute(stmt).rowcount or 0


def logout(db: Session, principal: Principal, *, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    if principal.session_id is not None:
        db.execute(
            update(AuthSession)
            .where(AuthSession.id == principal.session_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason="logout")
            .execution_options(synchronize_session=False)
        )
    user = db.get(User, principal.user_id)
    record_auth_event(
        db, "logout", actor=user, target=user, details={"session_id": principal.session_id}
    )
    db.commit()


def change_password(
    db: Session,
    settings: Settings,
    limiter: SlidingWindowLimiter,
    principal: Principal,
    *,
    current_password: str,
    new_password: str,
    now: datetime | None = None,
) -> User:
    now = now or datetime.now(UTC)
    key = f"password:{principal.user_id}"
    if limiter.blocked(key):
        raise TooManyRequestsError(TOO_MANY_ATTEMPTS, code="too_many_attempts")
    user = db.get(User, principal.user_id)
    if user is None:  # pragma: no cover - the session was just validated
        raise AuthenticationError()
    if settings.demo_mode and user.username in DEMO_USERNAMES:
        raise ForbiddenError(
            "Demo accounts are shared, so their password cannot be changed.",
            code="demo_account",
        )
    if not verify_password(current_password, user.password_hash):
        limiter.hit(key)
        record_auth_event(
            db,
            "password_change_failed",
            actor=user,
            target=user,
            success=False,
            details={"reason": "wrong_current_password"},
        )
        db.commit()
        raise BusinessRuleError(
            "The current password is not correct.",
            code="invalid_current_password",
            details=[{"field": "current_password"}],
        )
    problem = password_problem(new_password, username=user.username)
    if problem is None and new_password == current_password:
        problem = "Choose a password different from the current one."
    if problem is not None:
        raise BusinessRuleError(
            problem, code="weak_password", details=[{"field": "new_password"}]
        )
    limiter.reset(key)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.password_changed_at = now
    ended = revoke_user_sessions(
        db, user.id, "password_changed", now=now, keep_session_id=principal.session_id
    )
    record_auth_event(
        db, "password_changed", actor=user, target=user, details={"other_sessions_ended": ended}
    )
    db.commit()
    db.refresh(user)
    return user


__all__ = [
    "Principal",
    "SignIn",
    "authenticate",
    "change_password",
    "hash_session_token",
    "login",
    "logout",
    "principal_for",
    "revoke_user_sessions",
]
