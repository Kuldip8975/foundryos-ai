"""Accounts, sessions and access audit (Module 5).

    users ──< user_machine_assignments >── machines
      └───< auth_sessions
    auth_audit_events (append-only; names are copied so history survives)

Design rules:
* there is no self-registration: only an admin (or the one-time bootstrap
  command) creates accounts;
* passwords are stored only as salted scrypt hashes (app.core.passwords);
* a session is an opaque random token. Only its SHA-256 is stored, so a
  database leak does not reveal usable tokens. Sessions expire after an
  absolute lifetime and after inactivity, and are revoked on logout,
  deactivation and password change or reset;
* usernames never change, so audit records stay attributable;
* operators see and record data only for machines assigned to them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import BigIntPK, UTCDateTime, utcnow
from app.models.enums import UserRole, sql_in_list
from app.models.reports import JsonDocument

USERNAME_LENGTH = 100
EMAIL_LENGTH = 254
DISPLAY_NAME_LENGTH = 200
ROLE_LENGTH = 30
PASSWORD_HASH_LENGTH = 255
TOKEN_HASH_LENGTH = 64


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"role IN ({sql_in_list(UserRole)})", name="role_valid"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count_non_negative"),
        CheckConstraint("username = lower(username)", name="username_lowercase"),
        CheckConstraint("email IS NULL OR email = lower(email)", name="email_lowercase"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    username: Mapped[str] = mapped_column(String(USERNAME_LENGTH), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(EMAIL_LENGTH), unique=True)
    display_name: Mapped[str] = mapped_column(String(DISPLAY_NAME_LENGTH), nullable=False)
    role: Mapped[str] = mapped_column(String(ROLE_LENGTH), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(PASSWORD_HASH_LENGTH), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    password_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deactivated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by_id: Mapped[int | None] = mapped_column(
        BigIntPK, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    machine_assignments: Mapped[list[UserMachineAssignment]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="UserMachineAssignment.machine_id",
    )

    @property
    def machine_ids(self) -> list[int]:
        return [assignment.machine_id for assignment in self.machine_assignments]

    def __repr__(self) -> str:  # never print the password hash
        return f"User(id={self.id!r}, username={self.username!r}, role={self.role!r})"


class UserMachineAssignment(Base):
    """A machine an operator works on. Operators only see and record data for these."""

    __tablename__ = "user_machine_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "machine_id", name="uq_user_machine_assignments_user_machine"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    machine_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = _created_at()

    user: Mapped[User] = relationship(back_populates="machine_assignments")


class AuthSession(Base):
    """One signed-in browser session. Only the token's SHA-256 is stored."""

    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_active", "user_id", "revoked_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(
        String(TOKEN_HASH_LENGTH), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = _created_at()
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoke_reason: Mapped[str | None] = mapped_column(String(30))

    user: Mapped[User] = relationship()

    def __repr__(self) -> str:  # never print the token hash
        return f"AuthSession(id={self.id!r}, user_id={self.user_id!r})"


class AuthAuditEvent(Base):
    """Append-only record of sign-ins and access administration.

    ``details`` holds ids, codes and counts only — never passwords, tokens,
    token hashes or the text typed into a failed sign-in.
    """

    __tablename__ = "auth_audit_events"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        BigIntPK, ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_username: Mapped[str | None] = mapped_column(String(USERNAME_LENGTH))
    target_user_id: Mapped[int | None] = mapped_column(
        BigIntPK, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    target_username: Mapped[str | None] = mapped_column(String(USERNAME_LENGTH))
    success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    details: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
    )