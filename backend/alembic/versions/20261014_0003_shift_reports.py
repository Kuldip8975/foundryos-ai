"""AI shift reports (Module 3).

Adds one table, ``shift_reports``. Existing tables and rows are not touched.
Self-contained on purpose: it does not import application models.

Revision ID: 0003_shift_reports
Revises: 0002_manufacturing_data
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_shift_reports"
down_revision: str | Sequence[str] | None = "0002_manufacturing_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "shift_reports",
        sa.Column("id", ID, nullable=False),
        sa.Column("request_key", sa.String(200), nullable=False),
        sa.Column("production_date", sa.Date(), nullable=False),
        sa.Column("shift", sa.String(16), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_source", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("prompt_version", sa.String(30), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("metrics", JSON_DOCUMENT, nullable=False),
        sa.Column("content", JSON_DOCUMENT, nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_message", sa.String(300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shift_reports")),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name=op.f("ck_shift_reports_status_valid"),
        ),
        sa.CheckConstraint(
            "data_source IS NULL OR data_source IN ('manual', 'import', 'synthetic')",
            name=op.f("ck_shift_reports_data_source_valid"),
        ),
        sa.CheckConstraint(
            "(window_start IS NULL AND window_end IS NULL) OR "
            "(window_start IS NOT NULL AND window_end IS NOT NULL AND window_end > window_start)",
            name=op.f("ck_shift_reports_window_valid"),
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR content IS NOT NULL",
            name=op.f("ck_shift_reports_completed_has_content"),
        ),
    )
    op.create_index(
        "ix_shift_reports_date_shift", "shift_reports", ["production_date", "shift"]
    )
    op.create_index(op.f("ix_shift_reports_status"), "shift_reports", ["status"])
    # At most one in-flight generation per request key (duplicate prevention).
    op.create_index(
        "uq_shift_reports_pending_request",
        "shift_reports",
        ["request_key"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_table("shift_reports")  # drops its indexes and constraints too