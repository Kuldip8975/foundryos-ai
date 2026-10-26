"""The Alembic migration chain matches the ORM models.

Runs the real migration scripts against an in-memory SQLite database (never a
developer database) by handing env.py an open connection.
"""

from __future__ import annotations

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect

from alembic import command
from app.db.models import Base
from app.services.health import expected_migration_heads
from tests.conftest import make_sqlite_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
MODULE_1_TABLES = {
    "machines",
    "products",
    "defect_categories",
    "production_records",
    "quality_inspections",
    "machine_downtime_events",
    "maintenance_requests",
}


def _alembic(connection: Connection) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["connection"] = connection
    return cfg


MODULE_3_TABLES = {"shift_reports"}
MODULE_4_TABLES = {
    "workflow_sessions",
    "workflow_steps",
    "action_proposals",
    "action_approvals",
    "workflow_audit_events",
}


MODULE_5_TABLES = {
    "users",
    "user_machine_assignments",
    "auth_sessions",
    "auth_audit_events",
}


def test_head_is_module_5_revision() -> None:
    assert expected_migration_heads() == frozenset({"0005_auth_rbac"})


def test_upgrade_creates_schema_identical_to_models() -> None:
    engine = make_sqlite_engine()
    try:
        with engine.begin() as connection:
            command.upgrade(_alembic(connection), "head")
            tables = set(inspect(connection).get_table_names())
            assert MODULE_1_TABLES | MODULE_3_TABLES | MODULE_4_TABLES | MODULE_5_TABLES <= tables
            # Types are compared on PostgreSQL by the integration test; SQLite
            # reflection reports storage classes, so only structure is compared here.
            context = MigrationContext.configure(connection, opts={"compare_type": False})
            differences = compare_metadata(context, Base.metadata)
        assert differences == [], differences
    finally:
        engine.dispose()


def test_downgrade_to_baseline_removes_module_1_tables() -> None:
    engine = make_sqlite_engine()
    try:
        with engine.begin() as connection:
            cfg = _alembic(connection)
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "0001_baseline")
            remaining = set(inspect(connection).get_table_names())
        assert remaining.isdisjoint(
            MODULE_1_TABLES | MODULE_3_TABLES | MODULE_4_TABLES | MODULE_5_TABLES
        )
        assert "alembic_version" in remaining
    finally:
        engine.dispose()


def test_downgrade_of_module_3_keeps_manufacturing_data_tables() -> None:
    engine = make_sqlite_engine()
    try:
        with engine.begin() as connection:
            cfg = _alembic(connection)
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "0002_manufacturing_data")
            remaining = set(inspect(connection).get_table_names())
        assert remaining.isdisjoint(MODULE_3_TABLES | MODULE_4_TABLES | MODULE_5_TABLES)
        assert MODULE_1_TABLES <= remaining
    finally:
        engine.dispose()


def test_downgrade_of_module_4_keeps_earlier_tables() -> None:
    engine = make_sqlite_engine()
    try:
        with engine.begin() as connection:
            cfg = _alembic(connection)
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "0003_shift_reports")
            remaining = set(inspect(connection).get_table_names())
        assert remaining.isdisjoint(MODULE_4_TABLES | MODULE_5_TABLES)
        assert MODULE_1_TABLES | MODULE_3_TABLES <= remaining
    finally:
        engine.dispose()


def test_downgrade_of_module_5_keeps_earlier_tables() -> None:
    engine = make_sqlite_engine()
    try:
        with engine.begin() as connection:
            cfg = _alembic(connection)
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "0004_workflow_agent")
            remaining = set(inspect(connection).get_table_names())
        assert remaining.isdisjoint(MODULE_5_TABLES)
        assert MODULE_1_TABLES | MODULE_3_TABLES | MODULE_4_TABLES <= remaining
    finally:
        engine.dispose()