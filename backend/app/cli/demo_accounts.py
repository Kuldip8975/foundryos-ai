"""Create or reset the shared accounts of a PUBLIC DEMO deployment.

    DEMO_ACCOUNT_PASSWORD='...' python -m app.cli.demo_accounts

Creates (or resets) three accounts that visitors can use on the sign-in page:

    demo.operator    operator, assigned to the first two active machines
    demo.supervisor  supervisor
    demo.manager     production manager

All use the password in DEMO_ACCOUNT_PASSWORD (it is published on the demo
sign-in page, so never reuse a real password). Running it again resets the
password, unlocks the accounts and ends their sessions, which suits a daily
cron job. No admin account is ever created or published by this command.

Use only with clearly labelled synthetic data, and set DEMO_MODE=true so the
demo accounts cannot change their (shared) password.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.passwords import hash_password, password_problem
from app.db.session import get_engine
from app.models.auth import User, UserMachineAssignment
from app.models.enums import UserRole
from app.models.manufacturing import Machine
from app.services.auth.audit import record_auth_event
from app.services.auth.sessions import revoke_user_sessions
from app.services.health import check_readiness, expected_migration_heads

EXIT_OK, EXIT_INVALID, EXIT_NOT_READY = 0, 1, 3

DEMO_ACCOUNTS = (
    ("demo.operator", "Demo Operator", UserRole.OPERATOR),
    ("demo.supervisor", "Demo Supervisor", UserRole.SUPERVISOR),
    ("demo.manager", "Demo Production Manager", UserRole.PRODUCTION_MANAGER),
)
OPERATOR_MACHINES = 2


def main(
    argv: list[str] | None = None,
    *,
    engine: Engine | None = None,
    password: str | None = None,
    out: Callable[[str], None] = print,
) -> int:
    password = password if password is not None else os.environ.get("DEMO_ACCOUNT_PASSWORD", "")
    problem = password_problem(password) if password else "Set DEMO_ACCOUNT_PASSWORD."
    if problem is not None:
        out(f"Invalid DEMO_ACCOUNT_PASSWORD: {problem}")
        return EXIT_INVALID

    settings = get_settings()
    engine = engine or get_engine()
    readiness = check_readiness(engine, expected_migration_heads())
    if readiness.status != "ready":
        out("NOT READY : run `alembic upgrade head` first.")
        return EXIT_NOT_READY
    if not settings.demo_mode:
        out("WARNING   : DEMO_MODE is not true; demo accounts could change the shared password.")

    now = datetime.now(UTC)
    with Session(engine, expire_on_commit=False) as db:
        machine_ids = list(
            db.scalars(
                select(Machine.id)
                .where(Machine.is_active.is_(True))
                .order_by(Machine.code)
                .limit(OPERATOR_MACHINES)
            )
        )
        for username, name, role in DEMO_ACCOUNTS:
            user = db.scalar(select(User).where(User.username == username))
            created = user is None
            if user is None:
                user = User(username=username, display_name=name, role=role.value, password_hash="")
                db.add(user)
            user.display_name = name
            user.role = role.value
            user.password_hash = hash_password(password)
            user.is_active = True
            user.deactivated_at = None
            user.must_change_password = False
            user.failed_login_count = 0
            user.locked_until = None
            user.password_changed_at = now
            wanted = machine_ids if role is UserRole.OPERATOR else []
            keep = [a for a in user.machine_assignments if a.machine_id in wanted]
            have = {a.machine_id for a in keep}
            user.machine_assignments[:] = keep + [
                UserMachineAssignment(machine_id=m) for m in wanted if m not in have
            ]
            db.flush()
            if not created:
                revoke_user_sessions(db, user.id, "demo_reset", now=now)
            record_auth_event(
                db,
                "demo_account_created" if created else "demo_account_reset",
                actor_username="command-line",
                target=user,
                details={"role": role.value, "machine_count": len(wanted)},
            )
            out(f"{'Created' if created else 'Reset  '} {username:<16} ({role.value})")
        db.commit()
    out("Done. The password is the value of DEMO_ACCOUNT_PASSWORD (published on the sign-in page).")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
