"""Load the SYNTHETIC demonstration dataset.

    cd backend
    python -m app.cli.seed            # dry run: shows target and dataset size, writes nothing
    python -m app.cli.seed --apply    # inserts missing synthetic rows (safe to repeat)

Never runs automatically. Refuses when ENVIRONMENT=production and when the
database is not migrated to the current head. The password in DATABASE_URL
is never printed.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine
from app.services.health import check_readiness, expected_migration_heads
from app.services.seed import SeedRefusedError, build_dataset, seed_synthetic_data

EXIT_OK, EXIT_REFUSED, EXIT_NOT_READY = 0, 2, 3


def _target_description(database_url: str) -> str:
    url = make_url(database_url)
    return f"database {url.database!r} on {url.host or 'local socket'}:{url.port or 5432}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load SYNTHETIC demonstration data.")
    parser.add_argument(
        "--apply", action="store_true", help="Write to the database (default: dry run)"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    print("FoundryOS AI - SYNTHETIC demonstration data (not real company data)")
    print(f"Environment : {settings.environment}")
    print(f"Target      : {_target_description(settings.database_url)}")

    if settings.is_production:
        print("REFUSED     : synthetic data is never loaded when ENVIRONMENT=production.")
        return EXIT_REFUSED

    sizes = {table: len(rows) for table, rows in build_dataset().items()}
    for table, count in sizes.items():
        print(f"  {table:<26}{count:>5} synthetic rows")

    if not args.apply:
        print("Dry run     : nothing written. Re-run with --apply to insert missing rows.")
        return EXIT_OK

    engine = get_engine()
    readiness = check_readiness(engine, expected_migration_heads())
    if readiness.status != "ready":
        for check in readiness.checks:
            print(f"NOT READY   : {check.name}: {check.status} {check.detail or ''}".rstrip())
        print("Run `alembic upgrade head` first.")
        return EXIT_NOT_READY

    with Session(engine) as db:
        try:
            report = seed_synthetic_data(db, settings)
        except SeedRefusedError as exc:
            print(f"REFUSED     : {exc}")
            return EXIT_REFUSED

    for table in sizes:
        created = report.created.get(table, 0)
        existing = report.existing.get(table, 0)
        print(f"  {table:<26}created {created:>4}  already present {existing:>4}")
    print(f"Done        : {report.total_created} rows created.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())