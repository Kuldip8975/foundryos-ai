"""Baseline: empty schema.

Establishes the migration history (creates ``alembic_version``) without any
business tables. Module 1 adds the first schema on top of this revision.
The readiness probe uses this revision to confirm migrations have been applied.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-14
"""

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
