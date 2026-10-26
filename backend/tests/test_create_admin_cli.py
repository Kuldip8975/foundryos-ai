"""First-admin bootstrap command (Module 5): python -m app.cli.create_admin."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from alembic import command
from app.cli import create_admin
from app.core.passwords import verify_password
from app.models.auth import AuthAuditEvent, User
from tests.conftest import make_sqlite_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
GOOD = "Plant-admin-7731-teal"


@pytest.fixture
def migrated() -> Iterator[Engine]:
    engine = make_sqlite_engine()
    with engine.begin() as connection:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
    yield engine
    engine.dispose()


def run(engine: Engine, argv: list[str], answers: list[str] | None = None) -> tuple[int, str]:
    lines: list[str] = []
    replies = list(answers or [])
    code = create_admin.main(argv, engine=engine, ask=lambda _prompt: replies.pop(0),
                             out=lines.append)
    return code, "\n".join(lines)


def test_creates_the_first_admin_with_a_prompted_password(migrated: Engine) -> None:
    code, output = run(migrated, ["Root.Admin", "--name", "Plant Admin"], [GOOD, GOOD])
    assert code == create_admin.EXIT_OK, output
    assert GOOD not in output  # never printed
    with Session(migrated) as db:
        user = db.scalar(select(User))
        assert user is not None
        assert (user.username, user.role, user.is_active) == ("root.admin", "admin", True)
        assert user.must_change_password is False  # they chose it themselves
        assert verify_password(GOOD, user.password_hash)
        assert GOOD not in user.password_hash
        event = db.scalar(select(AuthAuditEvent))
        assert event is not None and event.event_type == "admin_bootstrapped"
        assert event.actor_username == "command-line"


def test_generated_password_is_shown_once_and_must_be_changed(migrated: Engine) -> None:
    code, output = run(migrated, ["admin", "--name", "Admin", "--generate-password"])
    assert code == create_admin.EXIT_OK
    generated = output.split("first sign-in):\n  ", 1)[1].splitlines()[0]
    with Session(migrated) as db:
        user = db.scalar(select(User))
        assert user is not None and user.must_change_password is True
        assert verify_password(generated, user.password_hash)


def test_refuses_when_an_admin_already_exists(migrated: Engine) -> None:
    assert run(migrated, ["admin", "--name", "Admin", "--generate-password"])[0] == 0
    code, output = run(migrated, ["second", "--name", "Second", "--generate-password"])
    assert code == create_admin.EXIT_REFUSED
    assert "already exists" in output
    with Session(migrated) as db:
        assert len(list(db.scalars(select(User)))) == 1


def test_weak_or_mismatched_passwords_are_not_accepted(migrated: Engine) -> None:
    code, output = run(
        migrated, ["admin", "--name", "Admin"],
        ["short", GOOD, "different-password-1", "adminadmin-1234"],
    )
    assert code == create_admin.EXIT_INVALID
    assert "at least 12" in output and "did not match" in output and "username" in output
    with Session(migrated) as db:
        assert db.scalar(select(User)) is None


def test_invalid_arguments_and_unmigrated_database_are_refused() -> None:
    engine = make_sqlite_engine()
    try:
        invalid = create_admin.EXIT_INVALID
        assert run(engine, ["x", "--name", "X", "--generate-password"])[0] == invalid
        bad_email = ["ok-name", "--name", "X", "--email", "nope", "--generate-password"]
        assert run(engine, bad_email)[0] == invalid
        code, output = run(engine, ["admin", "--name", "Admin", "--generate-password"])
        assert code == create_admin.EXIT_NOT_READY
        assert "alembic upgrade head" in output
    finally:
        engine.dispose()