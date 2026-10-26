"""Public demo accounts (python -m app.cli.demo_accounts) and DEMO_MODE."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from alembic import command
from app.cli import demo_accounts
from app.core.passwords import verify_password
from app.models.auth import User
from app.models.manufacturing import Machine
from tests.conftest import make_settings, make_sqlite_engine
from tests.helpers import API, error_code

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEMO_PASSWORD = "Public-demo-2026"  # noqa: S105 - test value


@pytest.fixture
def migrated() -> Iterator[Engine]:
    engine = make_sqlite_engine()
    with engine.begin() as connection:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
    with Session(engine) as db:
        db.add_all([Machine(code=f"M{i}", name=f"Machine {i}") for i in (3, 1, 2)])
        db.commit()
    yield engine
    engine.dispose()


def run(engine: Engine, password: str = DEMO_PASSWORD) -> tuple[int, str]:
    lines: list[str] = []
    code = demo_accounts.main([], engine=engine, password=password, out=lines.append)
    return code, "\n".join(lines)


def test_creates_three_demo_accounts_without_an_admin(migrated: Engine) -> None:
    code, output = run(migrated)
    assert code == 0, output
    assert DEMO_PASSWORD not in output
    with Session(migrated) as db:
        users = {u.username: u for u in db.scalars(select(User))}
        assert set(users) == {"demo.operator", "demo.supervisor", "demo.manager"}
        assert all(u.role != "admin" for u in users.values())
        assert all(not u.must_change_password for u in users.values())
        assert verify_password(DEMO_PASSWORD, users["demo.manager"].password_hash)
        codes = sorted(
            db.scalar(select(Machine.code).where(Machine.id == m))
            for m in users["demo.operator"].machine_ids
        )
        assert codes == ["M1", "M2"]
        assert users["demo.supervisor"].machine_ids == []


def test_running_again_resets_password_and_unlocks(migrated: Engine) -> None:
    assert run(migrated)[0] == 0
    with Session(migrated) as db:
        user = db.scalar(select(User).where(User.username == "demo.operator"))
        assert user is not None
        user.is_active = False
        user.password_hash = "changed"  # noqa: S105
        db.commit()
    code, output = run(migrated)
    assert code == 0 and "Reset" in output
    with Session(migrated) as db:
        user = db.scalar(select(User).where(User.username == "demo.operator"))
        assert user is not None and user.is_active
        assert verify_password(DEMO_PASSWORD, user.password_hash)
        assert len(user.machine_ids) == 2


def test_weak_or_missing_password_is_refused(migrated: Engine) -> None:
    assert run(migrated, "")[0] == demo_accounts.EXIT_INVALID
    assert run(migrated, "short")[0] == demo_accounts.EXIT_INVALID


def test_demo_accounts_cannot_change_the_shared_password(
    app: FastAPI, secured_api: TestClient, db_session: Session
) -> None:
    from app.services.auth.users import create_user

    app.state.settings = make_settings(demo_mode=True)
    create_user(
        db_session, make_settings(), None,
        {"username": "demo.supervisor", "display_name": "Demo", "role": "supervisor",
         "temporary_password": DEMO_PASSWORD, "require_password_change": False},
    )
    token = secured_api.post(
        f"{API}/auth/login", json={"username": "demo.supervisor", "password": DEMO_PASSWORD}
    ).json()["access_token"]
    response = secured_api.post(
        f"{API}/auth/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": DEMO_PASSWORD, "new_password": "Someone-else-2026"},
    )
    assert response.status_code == 403
    assert error_code(response) == "demo_account"
