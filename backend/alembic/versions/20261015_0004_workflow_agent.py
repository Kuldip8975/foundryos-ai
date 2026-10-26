"""Workflow assistant and human approval (Module 4).

Adds five tables: workflow_sessions, workflow_steps, action_proposals,
action_approvals and workflow_audit_events. Existing tables and rows are not
touched. Self-contained on purpose: it does not import application models.

Revision ID: 0004_workflow_agent
Revises: 0003_shift_reports
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_workflow_agent"
down_revision: str | Sequence[str] | None = "0003_shift_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
ROLES = "'viewer', 'operator', 'supervisor'"


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def upgrade() -> None:
    op.create_table(
        "workflow_sessions",
        sa.Column("id", ID, nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("actor_role", sa.String(20), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("answer", JSON_DOCUMENT, nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(30), nullable=False),
        sa.Column("tool_call_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "includes_synthetic_data", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_message", sa.String(300), nullable=True),
        _created_at(),
        _updated_at(),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_sessions")),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name=op.f("ck_workflow_sessions_status_valid"),
        ),
        sa.CheckConstraint(
            f"actor_role IN ({ROLES})", name=op.f("ck_workflow_sessions_actor_role_valid")
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR answer IS NOT NULL",
            name=op.f("ck_workflow_sessions_completed_has_answer"),
        ),
        sa.CheckConstraint(
            "tool_call_count >= 0",
            name=op.f("ck_workflow_sessions_tool_call_count_non_negative"),
        ),
    )
    op.create_index(op.f("ix_workflow_sessions_status"), "workflow_sessions", ["status"])
    op.create_index(
        "ix_workflow_sessions_actor_created", "workflow_sessions", ["actor", "created_at"]
    )

    op.create_table(
        "workflow_steps",
        sa.Column("id", ID, nullable=False),
        sa.Column("session_id", ID, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("arguments", JSON_DOCUMENT, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("evidence_id", sa.String(10), nullable=True),
        sa.Column("result", JSON_DOCUMENT, nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_message", sa.String(300), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_steps")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["workflow_sessions.id"],
            name=op.f("fk_workflow_steps_session_id_workflow_sessions"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "session_id", "sequence", name="uq_workflow_steps_session_sequence"
        ),
        sa.CheckConstraint(
            "status IN ('ok', 'rejected', 'error')", name=op.f("ck_workflow_steps_status_valid")
        ),
        sa.CheckConstraint(
            "(status = 'ok' AND evidence_id IS NOT NULL) "
            "OR (status <> 'ok' AND evidence_id IS NULL)",
            name=op.f("ck_workflow_steps_evidence_only_when_ok"),
        ),
    )

    op.create_table(
        "action_proposals",
        sa.Column("id", ID, nullable=False),
        sa.Column("session_id", ID, nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("arguments", JSON_DOCUMENT, nullable=False),
        sa.Column("preview", JSON_DOCUMENT, nullable=False),
        sa.Column("arguments_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("proposed_by", sa.String(100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", JSON_DOCUMENT, nullable=True),
        sa.Column("result_record_type", sa.String(50), nullable=True),
        sa.Column("result_record_id", ID, nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_message", sa.String(300), nullable=True),
        _created_at(),
        _updated_at(),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_action_proposals")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["workflow_sessions.id"],
            name=op.f("fk_action_proposals_session_id_workflow_sessions"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("session_id", name=op.f("uq_action_proposals_session_id")),
        sa.CheckConstraint(
            "status IN ('pending_approval', 'executed', 'rejected', 'expired', 'failed')",
            name=op.f("ck_action_proposals_status_valid"),
        ),
        sa.CheckConstraint(
            "status <> 'executed' OR (result_record_id IS NOT NULL AND executed_at IS NOT NULL)",
            name=op.f("ck_action_proposals_executed_has_record"),
        ),
    )
    op.create_index(op.f("ix_action_proposals_status"), "action_proposals", ["status"])

    op.create_table(
        "action_approvals",
        sa.Column("id", ID, nullable=False),
        sa.Column("proposal_id", ID, nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("actor_role", sa.String(20), nullable=False),
        sa.Column("arguments_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_action_approvals")),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["action_proposals.id"],
            name=op.f("fk_action_approvals_proposal_id_action_proposals"),
            ondelete="CASCADE",
        ),
        # One decision per proposal (replay protection) and one use per key (idempotency).
        sa.UniqueConstraint("proposal_id", name=op.f("uq_action_approvals_proposal_id")),
        sa.UniqueConstraint(
            "idempotency_key", name=op.f("uq_action_approvals_idempotency_key")
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name=op.f("ck_action_approvals_decision_valid"),
        ),
        sa.CheckConstraint(
            f"actor_role IN ({ROLES})", name=op.f("ck_action_approvals_actor_role_valid")
        ),
    )

    op.create_table(
        "workflow_audit_events",
        sa.Column("id", ID, nullable=False),
        sa.Column("session_id", ID, nullable=True),
        sa.Column("proposal_id", ID, nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("details", JSON_DOCUMENT, nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_audit_events")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["workflow_sessions.id"],
            name=op.f("fk_workflow_audit_events_session_id_workflow_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["action_proposals.id"],
            name=op.f("fk_workflow_audit_events_proposal_id_action_proposals"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        op.f("ix_workflow_audit_events_session_id"), "workflow_audit_events", ["session_id"]
    )
    op.create_index(
        op.f("ix_workflow_audit_events_proposal_id"), "workflow_audit_events", ["proposal_id"]
    )
    op.create_index(
        op.f("ix_workflow_audit_events_event_type"), "workflow_audit_events", ["event_type"]
    )


def downgrade() -> None:
    # Reverse dependency order. Dropping a table drops its indexes and constraints.
    op.drop_table("workflow_audit_events")
    op.drop_table("action_approvals")
    op.drop_table("action_proposals")
    op.drop_table("workflow_steps")
    op.drop_table("workflow_sessions")