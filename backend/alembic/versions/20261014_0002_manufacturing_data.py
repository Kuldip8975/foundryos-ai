"""Manufacturing data foundation (Module 1).

Creates master data (machines, products, defect_categories) and facts
(production_records, quality_inspections, machine_downtime_events,
maintenance_requests). Self-contained on purpose: it does not import
application models, so later model changes cannot alter this revision.

Revision ID: 0002_manufacturing_data
Revises: 0001_baseline
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_manufacturing_data"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DATA_SOURCES = "'manual', 'import', 'synthetic'"


def _provenance_columns() -> list[sa.Column]:
    return [
        sa.Column("data_source", sa.String(20), nullable=False, server_default=sa.text("'manual'")),
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
    ]


def _data_source_check(table: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        f"data_source IN ({DATA_SOURCES})", name=op.f(f"ck_{table}_data_source_valid")
    )


def _master_table(table: str, key: str) -> None:
    op.create_table(
        table,
        sa.Column("id", ID, nullable=False),
        sa.Column(key, sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_provenance_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint(key, name=op.f(f"uq_{table}_{key}")),
        _data_source_check(table),
    )


def upgrade() -> None:
    _master_table("machines", "code")
    _master_table("products", "part_number")
    _master_table("defect_categories", "code")

    op.create_table(
        "production_records",
        sa.Column("id", ID, nullable=False),
        sa.Column("external_ref", sa.String(100), nullable=True),
        sa.Column("production_date", sa.Date(), nullable=False),
        sa.Column("shift", sa.String(16), nullable=False),
        sa.Column("product_id", ID, nullable=False),
        sa.Column("machine_id", ID, nullable=True),
        sa.Column("target_quantity", sa.Integer(), nullable=False),
        sa.Column("actual_quantity", sa.Integer(), nullable=False),
        sa.Column("accepted_quantity", sa.Integer(), nullable=False),
        sa.Column("rejected_quantity", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *_provenance_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_production_records")),
        sa.UniqueConstraint("external_ref", name=op.f("uq_production_records_external_ref")),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_production_records_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_production_records_machine_id_machines"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "target_quantity >= 0 AND actual_quantity >= 0 "
            "AND accepted_quantity >= 0 AND rejected_quantity >= 0",
            name=op.f("ck_production_records_quantities_non_negative"),
        ),
        sa.CheckConstraint(
            "accepted_quantity + rejected_quantity <= actual_quantity",
            name=op.f("ck_production_records_accepted_rejected_within_actual"),
        ),
        _data_source_check("production_records"),
    )
    op.create_index(
        op.f("ix_production_records_production_date"), "production_records", ["production_date"]
    )
    op.create_index(
        op.f("ix_production_records_product_id"), "production_records", ["product_id"]
    )
    op.create_index(
        op.f("ix_production_records_machine_id"), "production_records", ["machine_id"]
    )
    op.create_index(
        op.f("ix_production_records_date_shift"),
        "production_records",
        ["production_date", "shift"],
    )

    op.create_table(
        "quality_inspections",
        sa.Column("id", ID, nullable=False),
        sa.Column("external_ref", sa.String(100), nullable=True),
        sa.Column("production_record_id", ID, nullable=False),
        sa.Column("inspected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("inspected_quantity", sa.Integer(), nullable=False),
        sa.Column("defect_quantity", sa.Integer(), nullable=False),
        sa.Column("defect_category_id", ID, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_provenance_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quality_inspections")),
        sa.UniqueConstraint("external_ref", name=op.f("uq_quality_inspections_external_ref")),
        sa.ForeignKeyConstraint(
            ["production_record_id"],
            ["production_records.id"],
            name=op.f("fk_quality_inspections_production_record_id_production_records"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["defect_category_id"],
            ["defect_categories.id"],
            name=op.f("fk_quality_inspections_defect_category_id_defect_categories"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "inspected_quantity > 0 AND defect_quantity >= 0 "
            "AND defect_quantity <= inspected_quantity",
            name=op.f("ck_quality_inspections_quantities_valid"),
        ),
        sa.CheckConstraint(
            "defect_quantity = 0 OR defect_category_id IS NOT NULL",
            name=op.f("ck_quality_inspections_defect_category_required"),
        ),
        _data_source_check("quality_inspections"),
    )
    op.create_index(
        op.f("ix_quality_inspections_production_record_id"),
        "quality_inspections",
        ["production_record_id"],
    )
    op.create_index(
        op.f("ix_quality_inspections_inspected_at"), "quality_inspections", ["inspected_at"]
    )
    op.create_index(
        op.f("ix_quality_inspections_defect_category_id"),
        "quality_inspections",
        ["defect_category_id"],
    )

    op.create_table(
        "machine_downtime_events",
        sa.Column("id", ID, nullable=False),
        sa.Column("external_ref", sa.String(100), nullable=True),
        sa.Column("machine_id", ID, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *_provenance_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_machine_downtime_events")),
        sa.UniqueConstraint("external_ref", name=op.f("uq_machine_downtime_events_external_ref")),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_machine_downtime_events_machine_id_machines"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('ongoing', 'resolved')",
            name=op.f("ck_machine_downtime_events_status_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'ongoing' AND ended_at IS NULL) "
            "OR (status = 'resolved' AND ended_at IS NOT NULL)",
            name=op.f("ck_machine_downtime_events_status_matches_end"),
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at",
            name=op.f("ck_machine_downtime_events_end_after_start"),
        ),
        _data_source_check("machine_downtime_events"),
    )
    op.create_index(
        op.f("ix_machine_downtime_events_started_at"), "machine_downtime_events", ["started_at"]
    )
    op.create_index(
        op.f("ix_machine_downtime_events_status"), "machine_downtime_events", ["status"]
    )
    op.create_index(
        op.f("ix_machine_downtime_events_machine_started"),
        "machine_downtime_events",
        ["machine_id", "started_at"],
    )

    op.create_table(
        "maintenance_requests",
        sa.Column("id", ID, nullable=False),
        sa.Column("external_ref", sa.String(100), nullable=True),
        sa.Column("machine_id", ID, nullable=False),
        sa.Column("issue_description", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_provenance_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maintenance_requests")),
        sa.UniqueConstraint("external_ref", name=op.f("uq_maintenance_requests_external_ref")),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["machines.id"],
            name=op.f("fk_maintenance_requests_machine_id_machines"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')",
            name=op.f("ck_maintenance_requests_priority_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'closed', 'cancelled')",
            name=op.f("ck_maintenance_requests_status_valid"),
        ),
        sa.CheckConstraint(
            "(status IN ('resolved', 'closed') AND resolved_at IS NOT NULL "
            "AND resolution_notes IS NOT NULL) "
            "OR (status NOT IN ('resolved', 'closed') AND resolved_at IS NULL)",
            name=op.f("ck_maintenance_requests_resolution_consistent"),
        ),
        _data_source_check("maintenance_requests"),
    )
    op.create_index(
        op.f("ix_maintenance_requests_machine_id"), "maintenance_requests", ["machine_id"]
    )
    op.create_index(
        op.f("ix_maintenance_requests_priority"), "maintenance_requests", ["priority"]
    )
    op.create_index(op.f("ix_maintenance_requests_status"), "maintenance_requests", ["status"])


def downgrade() -> None:
    # Reverse dependency order. Dropping a table drops its indexes and constraints.
    op.drop_table("maintenance_requests")
    op.drop_table("machine_downtime_events")
    op.drop_table("quality_inspections")
    op.drop_table("production_records")
    op.drop_table("defect_categories")
    op.drop_table("products")
    op.drop_table("machines")