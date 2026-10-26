"""Alembic migration environment.

Uses the application's own settings so migrations always target the same
database as the API, and the application's metadata for autogenerate.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import Connection, engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.db.models import Base  # imports every model so metadata is complete

config = context.config

# A caller (e.g. the migration test) may pass an open connection via
# config.attributes["connection"]; the CLI never does. In that case the
# caller owns logging, so the ini-file logging setup is skipped.
_provided_connection = config.attributes.get("connection")

if config.config_file_name is not None and _provided_connection is None:
    fileConfig(config.config_file_name)

# Escape '%' so ConfigParser interpolation doesn't mangle URL-encoded passwords.
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection (alembic upgrade --sql)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_with_connection(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if _provided_connection is not None:
        _run_with_connection(_provided_connection)
        return
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _run_with_connection(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()