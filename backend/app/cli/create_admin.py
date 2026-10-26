"""Create the FIRST admin account (Module 5). Run once, on the server.

    cd backend
    python -m app.cli.create_admin admin --name "Plant Admin"
        → asks for the password twice (nothing is echoed or stored in shell history)

    python -m app.cli.create_admin admin --name "Plant Admin" --generate-password
        → prints a one-time password; it must be changed at the first sign-in

Safety:
* refuses when an active admin already exists — further accounts, including
  other admins, are created by an admin in the web app (Admin → Users);
* refuses when the database is not migrated to the current head;
* the password is never printed (unless generated, then once), never logged,
  and stored only as a salted scrypt hash;
* there are no default or built-in credentials anywhere in the code.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.passwords import password_problem
from app.db.session import get_engine
from app.models.enums import UserRole
from app.schemas.auth import Email, Username
from app.schemas.common import Name
from app.services.auth.users import active_admin_count, create_user
from app.services.health import check_readiness, expected_migration_heads

EXIT_OK, EXIT_INVALID, EXIT_REFUSED, EXIT_NOT_READY = 0, 1, 2, 3
MAX_PROMPTS = 3


def _valid(adapter_type: object, value: str) -> str | None:
    try:
        return TypeAdapter(adapter_type).validate_python(value)
    except ValidationError:
        return None


def _ask_password(
    username: str, ask: Callable[[str], str], out: Callable[[str], None]
) -> str | None:
    for _ in range(MAX_PROMPTS):
        first = ask("Password for the new admin: ")
        problem = password_problem(first, username=username)
        if problem is not None:
            out(f"Not accepted: {problem}")
            continue
        if ask("Repeat the password: ") != first:
            out("The passwords did not match.")
            continue
        return first
    return None


def main(
    argv: list[str] | None = None,
    *,
    engine: Engine | None = None,
    ask: Callable[[str], str] = getpass.getpass,
    out: Callable[[str], None] = print,
) -> int:
    parser = argparse.ArgumentParser(description="Create the first FoundryOS admin account.")
    parser.add_argument("username", help="3-50 characters: a-z, 0-9, '.', '_' or '-'")
    parser.add_argument("--name", required=True, help='Display name, e.g. "Plant Admin"')
    parser.add_argument("--email", default=None, help="Work email (optional; can sign in with it)")
    parser.add_argument(
        "--generate-password",
        action="store_true",
        help="Print a one-time password instead of asking; it must be changed at first sign-in",
    )
    args = parser.parse_args(argv)

    username = _valid(Username, args.username)
    name = _valid(Name, args.name)
    email = _valid(Email, args.email) if args.email is not None else None
    if username is None or name is None or (args.email is not None and email is None):
        out("Invalid username, name or email. Usernames: 3-50 of a-z, 0-9, '.', '_', '-'.")
        return EXIT_INVALID

    settings = get_settings()
    engine = engine or get_engine()
    readiness = check_readiness(engine, expected_migration_heads())
    if readiness.status != "ready":
        for check in readiness.checks:
            out(f"NOT READY : {check.name}: {check.status} {check.detail or ''}".rstrip())
        out("Run `alembic upgrade head` first.")
        return EXIT_NOT_READY

    with Session(engine, expire_on_commit=False) as db:
        if active_admin_count(db) > 0:
            out("REFUSED   : an active admin already exists. Sign in as that admin and create")
            out("            further accounts in the web app (Admin → Users).")
            return EXIT_REFUSED

        password: str | None = None
        if not args.generate_password:
            password = _ask_password(username, ask, out)
            if password is None:
                out("No admin created.")
                return EXIT_INVALID

        user, generated = create_user(
            db,
            settings,
            None,
            {
                "username": username,
                "display_name": name,
                "email": email,
                "role": UserRole.ADMIN.value,
                "machine_ids": [],
                "temporary_password": password,
                # The admin typed this password themselves: no forced change.
                "require_password_change": password is None,
            },
            event_type="admin_bootstrapped",
        )

    out(f"Created admin '{user.username}' (id {user.id}).")
    if generated is not None:
        out("One-time password (shown once; it must be changed at the first sign-in):")
        out(f"  {generated}")
    out("Sign in to the web app with this account and create the other accounts there.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())