"""Private accounts, sessions and role-based access (Module 5).

Adds four tables: users, user_machine_assignments, auth_sessions and
auth_audit_events. Existing tables and rows are not touched. Self-contained on
purpose: it does not import application models.

No account is created here. Create the first admin afterwards with
``python -m app.cli.create_admin`` (see docs/module-5-auth-rbac.md).

Revision ID: 0005_auth_rbac
Revises: 0004_workflow_agent
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_auth_rbac"
down_revision: str | Sequence[str] | None = "0004_workflow_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
ROLES = "'operator', 'supervisor', 'production_manager', 'admin'"


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", ID, nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "must_change_password", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "failed_login_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", ID, nullable=True),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_users_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.CheckConstraint(f"role IN ({ROLES})", name=op.f("ck_users_role_valid")),
        sa.CheckConstraint(
            "failed_login_count >= 0", name=op.f("ck_users_failed_login_count_non_negative")
        ),
        sa.CheckConstraint(
            "username = lower(username)", name=op.f("ck_users_username_lowercase")
        ),
        sa.CheckConstraint(
            "email IS NULL OR email = lower(email)", name=op.f("ck_users_email_lowercase")
        ),
    )
    op.create_index(op.f("ix_users_role"), "users", ["role"])

    op.create_table(
        "user_machine_assignments",
        sa.Column("id", ID, nullable=False),
        sa.Column("user_id", ID, nullable=False),
        sa.Column("machine_id", ID, nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_machine_assignments")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_machine_assignments_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_user_machine_assignments_machine_id_machines"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id", "machine_id", name="uq_user_machine_assignments_user_machine"
        ),
    )
    op.create_index(
        op.f("ix_user_machine_assignments_machine_id"),
        "user_machine_assignments",
        ["machine_id"],
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", ID, nullable=False),
        sa.Column("user_id", ID, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        _created_at(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(30), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_sessions_token_hash")),
    )
    op.create_index(
        "ix_auth_sessions_user_active", "auth_sessions", ["user_id", "revoked_at"]
    )

    op.create_table(
        "auth_audit_events",
        sa.Column("id", ID, nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("actor_user_id", ID, nullable=True),
        sa.Column("actor_username", sa.String(100), nullable=True),
        sa.Column("target_user_id", ID, nullable=True),
        sa.Column("target_username", sa.String(100), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("details", JSON_DOCUMENT, nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_audit_events")),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_auth_audit_events_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name=op.f("fk_auth_audit_events_target_user_id_users"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        op.f("ix_auth_audit_events_event_type"), "auth_audit_events", ["event_type"]
    )
    op.create_index(
        op.f("ix_auth_audit_events_target_user_id"), "auth_audit_events", ["target_user_id"]
    )
    op.create_index(
        op.f("ix_auth_audit_events_created_at"), "auth_audit_events", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_auth_audit_events_created_at"), table_name="auth_audit_events")
    op.drop_index(op.f("ix_auth_audit_events_target_user_id"), table_name="auth_audit_events")
    op.drop_index(op.f("ix_auth_audit_events_event_type"), table_name="auth_audit_events")
    op.drop_table("auth_audit_events")
    op.drop_index("ix_auth_sessions_user_active", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index(
        op.f("ix_user_machine_assignments_machine_id"), table_name="user_machine_assignments"
    )
    op.drop_table("user_machine_assignments")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_table("users")