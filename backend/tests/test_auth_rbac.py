"""Private accounts, sessions and role-based access (Module 5).

These tests use ``secured_api``: real sign-in, real sessions and the real
permission checks (no test stand-in principal).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.routes.workflows import get_agent_model
from app.core import passwords
from app.core.config import Settings
from app.core.permissions import ROLE_PERMISSIONS, WORKFLOW_ROLE, Permission
from app.models.auth import AuthAuditEvent, AuthSession, User
from app.models.enums import DataSource, UserRole, WorkflowRole
from app.models.manufacturing import (
    Machine,
    MachineDowntimeEvent,
    MaintenanceRequest,
    Product,
    ProductionRecord,
    QualityInspection,
)
from app.services.auth.rate_limit import SlidingWindowLimiter
from app.services.auth.users import create_user, update_user
from app.services.workflow.permissions import ROLE_PERMISSIONS as WORKFLOW_PERMISSIONS
from app.services.workflow.permissions import Permission as WorkflowPermission
from tests.conftest import make_settings
from tests.helpers import API, error_code
from tests.test_api_workflows import FakeAgent, calls, final

PASSWORDS = {
    "ada": "Admin-pass-4821-blue",
    "sam": "Shift-lead-7731-green",
    "pia": "Plant-mgr-2290-amber",
    "olga": "Floor-op-5517-violet",
    "otto": "Floor-op-9902-orange",
}
ROLES = {
    "ada": UserRole.ADMIN,
    "sam": UserRole.SUPERVISOR,
    "pia": UserRole.PRODUCTION_MANAGER,
    "olga": UserRole.OPERATOR,
    "otto": UserRole.OPERATOR,
}
GENERIC_FAILURE = "Sign-in failed."


@pytest.fixture
def settings() -> Settings:  # overrides the conftest fixture for this module
    return make_settings()


# --------------------------------------------------------------------------- helpers


def add_user(
    db: Session,
    username: str,
    *,
    machine_ids: list[int] | None = None,
    must_change: bool = False,
    email: str | None = None,
) -> User:
    user, _ = create_user(
        db,
        make_settings(),
        None,
        {
            "username": username,
            "display_name": username.title(),
            "email": email,
            "role": ROLES[username].value,
            "machine_ids": machine_ids or [],
            "temporary_password": PASSWORDS[username],
        },
    )
    user.must_change_password = must_change
    db.commit()
    return user


def login(api: TestClient, username: str, password: str | None = None) -> Any:
    return api.post(
        f"{API}/auth/login",
        json={"username": username, "password": password or PASSWORDS[username]},
    )


def token_for(api: TestClient, username: str) -> str:
    response = login(api, username)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def plant(db_session: Session) -> dict[str, Any]:
    """Two machines with one record of each kind; synthetic-free, created via the ORM."""
    m1 = Machine(code="M1", name="Mill one")
    m2 = Machine(code="M2", name="Lathe two")
    part = Product(part_number="P-1", name="Part one")
    db_session.add_all([m1, m2, part])
    db_session.flush()
    day = datetime.now(UTC).date() - timedelta(days=1)
    records = {}
    for machine in (m1, m2):
        record = ProductionRecord(
            production_date=day, shift="A", product_id=part.id, machine_id=machine.id,
            target_quantity=100, actual_quantity=90, accepted_quantity=85, rejected_quantity=5,
            data_source=DataSource.MANUAL.value,
        )
        db_session.add(record)
        db_session.flush()
        records[machine.code] = record
        db_session.add(QualityInspection(
            production_record_id=record.id, inspected_at=datetime.now(UTC) - timedelta(hours=5),
            inspected_quantity=10, defect_quantity=0,
        ))
        db_session.add(MachineDowntimeEvent(
            machine_id=machine.id, started_at=datetime.now(UTC) - timedelta(hours=3),
            reason=f"Jam on {machine.code}", status="ongoing",
        ))
        db_session.add(MaintenanceRequest(
            machine_id=machine.id, issue_description=f"Check {machine.code}",
            priority="low", status="open",
        ))
    db_session.commit()
    return {
        "m1": m1.id,
        "m2": m2.id,
        "part": part.id,
        "records": {code: record.id for code, record in records.items()},
    }


@pytest.fixture
def people(db_session: Session, plant: dict[str, Any]) -> dict[str, User]:
    return {
        "ada": add_user(db_session, "ada", email="ada@plant.example"),
        "sam": add_user(db_session, "sam"),
        "pia": add_user(db_session, "pia"),
        "olga": add_user(db_session, "olga", machine_ids=[plant["m1"]]),
    }


def audit_types(db: Session) -> list[str]:
    db.expire_all()
    rows = db.scalars(select(AuthAuditEvent).order_by(AuthAuditEvent.id))
    return [event.event_type for event in rows]


# --------------------------------------------------------------------------- password hashing


def test_passwords_are_salted_scrypt_hashes() -> None:
    first = passwords.hash_password("correct horse battery")
    second = passwords.hash_password("correct horse battery")
    assert first != second  # random salt
    assert first.startswith("scrypt$")
    assert "correct horse" not in first
    assert passwords.verify_password("correct horse battery", first)
    assert not passwords.verify_password("correct horse batterY", first)
    assert not passwords.verify_password("x", "not-a-hash")
    assert not passwords.verify_password("x", "scrypt$99$8$1$AAAA$AAAA")  # out-of-range cost
    assert not passwords.verify_password("a" * 200, first)  # over the length limit


def test_production_cost_follows_owasp_and_old_hashes_are_upgraded() -> None:
    assert passwords.DEFAULT_PARAMS == passwords.ScryptParams(log2_n=15, r=8, p=3)
    current = passwords.hash_password("correct horse battery")
    assert not passwords.needs_rehash(current)
    weaker = "scrypt$11$8$1$" + current.split("$", 4)[4]
    assert passwords.needs_rehash(weaker)


@pytest.mark.parametrize(
    ("candidate", "fragment"),
    [
        ("short-1", "at least 12"),
        ("x" * 129, "at most 128"),
        (" leading-space-pass", "space"),
        ("aaaaaaaaaaaaaaaa", "repetitive"),
        ("Password1234", "too common"),
        ("my-olga-password", "username"),
    ],
)
def test_password_rules(candidate: str, fragment: str) -> None:
    problem = passwords.password_problem(candidate, username="olga")
    assert problem is not None and fragment in problem
    assert candidate not in problem  # messages never echo the password


def test_generated_temporary_passwords_satisfy_the_rules() -> None:
    generated = {passwords.generate_temporary_password() for _ in range(20)}
    assert len(generated) == 20
    assert all(passwords.password_problem(p) is None for p in generated)


# --------------------------------------------------------------------------- sign-in


def test_sign_in_returns_a_session_token_that_is_stored_only_as_a_hash(
    secured_api: TestClient, people: dict[str, User], db_session: Session
) -> None:
    response = login(secured_api, "olga")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    token = body["access_token"]
    assert body["token_type"] == "bearer"  # noqa: S105 - scheme name
    user = body["user"]
    assert user["username"] == "olga"
    assert user["role"] == "operator"
    assert user["home"] == "my-work"
    assert user["machine_scope"] == "assigned"
    assert [m["code"] for m in user["machines"]] == ["M1"]
    assert "production:record" in user["permissions"]
    assert "analytics:read" not in user["permissions"]
    assert "password" not in json.dumps(body).replace("must_change_password", "")

    stored = db_session.scalar(select(AuthSession))
    assert stored is not None
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in stored.token_hash
    me = secured_api.get(f"{API}/auth/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["username"] == "olga"


def test_sign_in_accepts_the_work_email_case_insensitively(
    secured_api: TestClient, people: dict[str, User]
) -> None:
    response = login(secured_api, "  ADA@Plant.Example ", PASSWORDS["ada"])
    assert response.status_code == 200
    assert response.json()["user"]["home"] == "admin"


@pytest.mark.parametrize("case", ["unknown", "wrong-password", "deactivated"])
def test_failed_sign_ins_share_one_generic_answer(
    secured_api: TestClient, people: dict[str, User], db_session: Session, case: str
) -> None:
    if case == "deactivated":
        people["sam"].is_active = False
        db_session.commit()
    username, password = {
        "unknown": ("nobody", "whatever-password-1"),
        "wrong-password": ("sam", "not-sams-password-1"),
        "deactivated": ("sam", PASSWORDS["sam"]),
    }[case]
    response = login(secured_api, username, password)
    assert response.status_code == 401
    assert error_code(response) == "invalid_credentials"
    assert response.json()["error"]["message"].startswith(GENERIC_FAILURE)
    assert "login_failed" in audit_types(db_session)


def test_repeated_failures_lock_the_account_temporarily(
    secured_api: TestClient, people: dict[str, User], db_session: Session
) -> None:
    for _ in range(5):  # AUTH_MAX_FAILED_LOGINS default
        assert login(secured_api, "sam", "wrong-password-xyz").status_code == 401
    # Even the right password is refused while locked, with the same generic answer.
    locked = login(secured_api, "sam")
    assert locked.status_code == 401
    assert error_code(locked) == "invalid_credentials"
    assert "account_locked" in audit_types(db_session)

    db_session.execute(
        update(User).where(User.username == "sam").values(
            locked_until=datetime.now(UTC) - timedelta(seconds=1)
        )
    )
    db_session.commit()
    assert login(secured_api, "sam").status_code == 200


def test_sign_in_attempts_are_rate_limited_per_client(
    app: FastAPI, secured_api: TestClient, people: dict[str, User]
) -> None:
    app.state.login_limiter = SlidingWindowLimiter(attempts=3, window_seconds=60)
    for name in ("x1", "x2", "x3"):
        assert login(secured_api, name, "whatever-password-1").status_code == 401
    blocked = login(secured_api, "sam")
    assert blocked.status_code == 429
    assert error_code(blocked) == "too_many_attempts"


def api_operations(app: FastAPI) -> list[tuple[str, str]]:
    """Every (method, path) the API serves, from its OpenAPI description."""
    return [
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    ]


def test_there_is_no_public_sign_up(app: FastAPI) -> None:
    operations = api_operations(app)
    words = ("register", "signup", "sign-up", "invite")
    assert not [path for _, path in operations if any(w in path for w in words)]
    auth_posts = {path for method, path in operations if path.startswith(f"{API}/auth")
                  and method == "POST"}
    assert auth_posts == {f"{API}/auth/login", f"{API}/auth/logout", f"{API}/auth/password"}


# ------------------------------------------------------------------- every endpoint is protected

PUBLIC = {f"{API}/health/live", f"{API}/health/ready", f"{API}/auth/login"}


def test_every_endpoint_except_health_and_login_requires_a_session(
    app: FastAPI, secured_api: TestClient
) -> None:
    checked = 0
    for method, template in api_operations(app):
        if template in PUBLIC:
            continue
        path = re.sub(r"\{[a-z_]+\}", "1", template)
        response = secured_api.request(method, path, json={})
        assert response.status_code == 401, (method, template, response.text)
        checked += 1
    assert checked >= 40


# --------------------------------------------------------------------------- sessions


def test_logout_ends_the_session(secured_api: TestClient, people: dict[str, User]) -> None:
    token = token_for(secured_api, "sam")
    assert secured_api.post(f"{API}/auth/logout", headers=bearer(token)).status_code == 204
    after = secured_api.get(f"{API}/auth/me", headers=bearer(token))
    assert after.status_code == 401
    assert error_code(after) == "session_revoked"


@pytest.mark.parametrize("kind", ["absolute", "idle"])
def test_sessions_expire(
    secured_api: TestClient, people: dict[str, User], db_session: Session, kind: str
) -> None:
    token = token_for(secured_api, "pia")
    past = datetime.now(UTC) - timedelta(minutes=31)
    values = {"expires_at": past} if kind == "absolute" else {"last_seen_at": past}
    db_session.execute(update(AuthSession).values(**values))
    db_session.commit()
    response = secured_api.get(f"{API}/analytics/dashboard", headers=bearer(token))
    assert response.status_code == 401
    assert error_code(response) == "session_expired"
    assert response.headers["www-authenticate"] == "Bearer"
    # Stays expired (it was revoked), and the event is audited.
    again = secured_api.get(f"{API}/auth/me", headers=bearer(token))
    assert error_code(again) == "session_expired"
    assert "session_expired" in audit_types(db_session)


@pytest.mark.parametrize(
    "header",
    ["", "Bearer", "Bearer short", "Basic abc", "Bearer " + "x" * 43, "Bearer " + "y" * 400],
)
def test_malformed_or_unknown_tokens_are_refused(
    secured_api: TestClient, people: dict[str, User], header: str
) -> None:
    response = secured_api.get(f"{API}/auth/me", headers={"Authorization": header})
    assert response.status_code == 401
    assert error_code(response) == "unauthorized"


# --------------------------------------------------------------------------- first sign-in


def test_temporary_password_must_be_changed_before_any_work(
    secured_api: TestClient, plant: dict[str, Any], db_session: Session
) -> None:
    add_user(db_session, "sam", must_change=True)
    first = token_for(secured_api, "sam")
    other_device = token_for(secured_api, "sam")
    me = secured_api.get(f"{API}/auth/me", headers=bearer(first)).json()
    assert me["must_change_password"] is True
    blocked = secured_api.get(f"{API}/maintenance-requests", headers=bearer(first))
    assert blocked.status_code == 403
    assert error_code(blocked) == "password_change_required"

    change = f"{API}/auth/password"
    wrong = secured_api.post(
        change, headers=bearer(first),
        json={"current_password": "not-the-password", "new_password": "a-brand-new-pass-1"},
    )
    assert wrong.status_code == 422 and error_code(wrong) == "invalid_current_password"
    weak = secured_api.post(
        change, headers=bearer(first),
        json={"current_password": PASSWORDS["sam"], "new_password": "short"},
    )
    assert weak.status_code == 422 and error_code(weak) == "weak_password"
    same = secured_api.post(
        change, headers=bearer(first),
        json={"current_password": PASSWORDS["sam"], "new_password": PASSWORDS["sam"]},
    )
    assert same.status_code == 422

    done = secured_api.post(
        change, headers=bearer(first),
        json={"current_password": PASSWORDS["sam"], "new_password": "a-brand-new-pass-1"},
    )
    assert done.status_code == 200, done.text
    assert done.json()["must_change_password"] is False
    assert secured_api.get(f"{API}/maintenance-requests", headers=bearer(first)).status_code == 200
    # Other sessions end when the password changes.
    assert secured_api.get(f"{API}/auth/me", headers=bearer(other_device)).status_code == 401
    assert login(secured_api, "sam").status_code == 401
    assert login(secured_api, "sam", "a-brand-new-pass-1").status_code == 200


# --------------------------------------------------------------------------- role permissions


def test_permission_table_is_explicit_and_least_privilege() -> None:
    assert set(ROLE_PERMISSIONS) == set(UserRole)
    admin = ROLE_PERMISSIONS[UserRole.ADMIN]
    assert admin == {Permission.MACHINES_READ, Permission.USERS_MANAGE, Permission.AUDIT_READ}
    for role in (UserRole.OPERATOR, UserRole.SUPERVISOR, UserRole.PRODUCTION_MANAGER):
        assert Permission.USERS_MANAGE not in ROLE_PERMISSIONS[role]
        assert Permission.AUDIT_READ not in ROLE_PERMISSIONS[role]
    assert Permission.ANALYTICS_READ not in ROLE_PERMISSIONS[UserRole.OPERATOR]
    assert Permission.PRODUCTION_RECORD not in ROLE_PERMISSIONS[UserRole.PRODUCTION_MANAGER]
    # Only supervisors approve; that matches the Module 4 workflow role exactly.
    approvers = {
        role for role, perms in ROLE_PERMISSIONS.items() if Permission.ACTIONS_APPROVE in perms
    }
    assert approvers == {UserRole.SUPERVISOR}
    for role, workflow_role in WORKFLOW_ROLE.items():
        can_decide = workflow_role is not None and (
            WorkflowPermission.DECIDE_ACTIONS in WORKFLOW_PERMISSIONS[workflow_role]
        )
        assert can_decide == (Permission.ACTIONS_APPROVE in ROLE_PERMISSIONS[role])
        assert (workflow_role is not None) == (Permission.ASSISTANT_USE in ROLE_PERMISSIONS[role])


MATRIX: list[tuple[str, str, str, int]] = [
    # (user, method, path, expected status) — paths use {m1}/{m2}/{part}
    ("olga", "GET", "/analytics/dashboard", 403),
    ("olga", "GET", "/shift-reports", 403),
    ("olga", "GET", "/admin/users", 403),
    ("olga", "POST", "/machines", 403),
    ("olga", "POST", "/maintenance-requests", 403),
    ("sam", "GET", "/analytics/dashboard", 200),
    ("sam", "GET", "/shift-reports", 200),
    ("sam", "GET", "/admin/users", 403),
    ("sam", "GET", "/admin/audit-events", 403),
    ("sam", "POST", "/machines", 403),
    ("pia", "GET", "/analytics/dashboard", 200),
    ("pia", "GET", "/shift-reports", 200),
    ("pia", "POST", "/production-records", 403),
    ("pia", "POST", "/downtime-events", 403),
    ("pia", "POST", "/maintenance-requests", 403),
    ("pia", "GET", "/admin/users", 403),
    ("ada", "GET", "/admin/users", 200),
    ("ada", "GET", "/admin/audit-events", 200),
    ("ada", "GET", "/machines", 200),
    ("ada", "GET", "/analytics/dashboard", 403),
    ("ada", "GET", "/production-records", 403),
    ("ada", "GET", "/downtime-events", 403),
    ("ada", "GET", "/maintenance-requests", 403),
    ("ada", "GET", "/shift-reports", 403),
    ("ada", "POST", "/machines", 403),
]


@pytest.mark.parametrize(("user", "method", "path", "expected"), MATRIX)
def test_role_permission_matrix(
    secured_api: TestClient,
    people: dict[str, User],
    user: str,
    method: str,
    path: str,
    expected: int,
) -> None:
    token = token_for(secured_api, user)
    response = secured_api.request(method, f"{API}{path}", headers=bearer(token), json={})
    if expected == 403:
        assert response.status_code == 403, response.text
        assert error_code(response) == "forbidden"
    else:
        assert response.status_code == expected, response.text


def test_roles_with_write_permissions_can_write(
    secured_api: TestClient, people: dict[str, User], plant: dict[str, Any]
) -> None:
    pia = bearer(token_for(secured_api, "pia"))
    created = secured_api.post(f"{API}/machines", headers=pia, json={"code": "M3", "name": "New"})
    assert created.status_code == 201, created.text
    sam = bearer(token_for(secured_api, "sam"))
    request = secured_api.post(
        f"{API}/maintenance-requests", headers=sam,
        json={"machine_id": plant["m2"], "issue_description": "Belt check", "priority": "low"},
    )
    assert request.status_code == 201, request.text


def test_a_role_in_the_request_body_is_ignored(
    secured_api: TestClient, people: dict[str, User]
) -> None:
    token = token_for(secured_api, "olga")
    response = secured_api.get(
        f"{API}/analytics/dashboard",
        headers={**bearer(token), "X-Role": "admin"},
        params={"role": "supervisor"},
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- operator data scope


def test_operators_only_see_their_assigned_machines(
    secured_api: TestClient, people: dict[str, User], plant: dict[str, Any]
) -> None:
    olga = bearer(token_for(secured_api, "olga"))
    machines = secured_api.get(f"{API}/machines", headers=olga).json()
    assert [m["code"] for m in machines["items"]] == ["M1"]
    assert secured_api.get(f"{API}/machines/{plant['m2']}", headers=olga).status_code == 404
    for path in ("/production-records", "/downtime-events", "/maintenance-requests",
                 "/quality-inspections"):
        body = secured_api.get(f"{API}{path}", headers=olga).json()
        assert body["total"] == 1, path
    # Asking for the other machine by filter returns nothing rather than its data.
    filtered = secured_api.get(
        f"{API}/downtime-events", headers=olga, params={"machine_id": plant["m2"]}
    ).json()
    assert filtered["total"] == 0

    sam = bearer(token_for(secured_api, "sam"))
    assert secured_api.get(f"{API}/downtime-events", headers=sam).json()["total"] == 2


def test_operators_cannot_read_or_record_data_for_other_machines(
    secured_api: TestClient, people: dict[str, User], plant: dict[str, Any], db_session: Session
) -> None:
    olga = bearer(token_for(secured_api, "olga"))
    other_record = plant["records"]["M2"]
    other_event = db_session.scalar(
        select(MachineDowntimeEvent.id).where(MachineDowntimeEvent.machine_id == plant["m2"])
    )
    assert secured_api.get(
        f"{API}/production-records/{other_record}", headers=olga
    ).status_code == 404
    assert secured_api.get(f"{API}/downtime-events/{other_event}", headers=olga).status_code == 404
    patched = secured_api.patch(
        f"{API}/downtime-events/{other_event}", headers=olga, json={"reason": "edited"}
    )
    assert patched.status_code == 404

    wrong_machine = secured_api.post(
        f"{API}/downtime-events", headers=olga,
        json={"machine_id": plant["m2"], "started_at": "2026-01-10T08:00:00Z", "reason": "x"},
    )
    assert wrong_machine.status_code == 403
    assert error_code(wrong_machine) == "machine_not_assigned"

    no_machine = secured_api.post(
        f"{API}/production-records", headers=olga,
        json={"production_date": "2026-01-10", "shift": "A", "product_id": plant["part"],
              "target_quantity": 10, "actual_quantity": 10, "accepted_quantity": 10,
              "rejected_quantity": 0},
    )
    assert no_machine.status_code == 422
    assert error_code(no_machine) == "machine_required"

    inspection = secured_api.post(
        f"{API}/quality-inspections", headers=olga,
        json={"production_record_id": other_record, "inspected_at": "2026-01-10T09:00:00Z",
              "inspected_quantity": 5, "defect_quantity": 0},
    )
    assert inspection.status_code == 422
    assert error_code(inspection) == "invalid_reference"

    own = secured_api.post(
        f"{API}/downtime-events", headers=olga,
        json={"machine_id": plant["m1"], "started_at": "2026-01-10T08:00:00Z",
              "ended_at": "2026-01-10T08:30:00Z", "reason": "Tool change"},
    )
    assert own.status_code == 201, own.text


def test_reassigning_machines_takes_effect_immediately(
    secured_api: TestClient, people: dict[str, User], plant: dict[str, Any]
) -> None:
    olga = bearer(token_for(secured_api, "olga"))
    ada = bearer(token_for(secured_api, "ada"))
    changed = secured_api.patch(
        f"{API}/admin/users/{people['olga'].id}", headers=ada,
        json={"machine_ids": [plant["m2"]]},
    )
    assert changed.status_code == 200, changed.text
    machines = secured_api.get(f"{API}/machines", headers=olga).json()
    assert [m["code"] for m in machines["items"]] == ["M2"]


# --------------------------------------------------------------------------- admin provisioning


def test_admin_creates_accounts_with_a_one_time_password(
    secured_api: TestClient, people: dict[str, User], plant: dict[str, Any], db_session: Session
) -> None:
    ada = bearer(token_for(secured_api, "ada"))
    response = secured_api.post(
        f"{API}/admin/users", headers=ada,
        json={"username": "Otto", "display_name": "Otto Operator", "role": "operator",
              "machine_ids": [plant["m2"]]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    temporary = body["temporary_password"]
    assert passwords.password_problem(temporary) is None
    assert body["user"]["username"] == "otto"  # normalised
    assert body["user"]["must_change_password"] is True
    assert body["user"]["machine_ids"] == [plant["m2"]]
    assert "password_hash" not in json.dumps(body)

    listed = secured_api.get(f"{API}/admin/users", headers=ada).json()
    assert "otto" in [u["username"] for u in listed["items"]]
    assert temporary not in json.dumps(listed)

    first = login(secured_api, "otto", temporary)
    assert first.status_code == 200
    assert first.json()["user"]["must_change_password"] is True

    stored = db_session.scalar(select(User).where(User.username == "otto"))
    assert stored is not None and stored.created_by_id == people["ada"].id
    assert temporary not in stored.password_hash


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"username": "sam", "display_name": "Dup", "role": "supervisor"}, 409, "username_taken"),
        ({"username": "new1", "display_name": "N", "role": "supervisor",
          "machine_ids": [1]}, 422, "machines_not_applicable"),
        ({"username": "new2", "display_name": "N", "role": "operator",
          "machine_ids": [999]}, 422, "invalid_reference"),
        ({"username": "new3", "display_name": "N", "role": "operator",
          "temporary_password": "short"}, 422, "weak_password"),
        ({"username": "new4", "display_name": "N", "role": "superuser"}, 422, "validation_error"),
        ({"username": "x", "display_name": "N", "role": "operator"}, 422, "validation_error"),
        ({"username": "new5", "display_name": "N", "role": "operator",
          "is_active": True}, 422, "validation_error"),
    ],
)
def test_account_creation_is_validated(
    secured_api: TestClient,
    people: dict[str, User],
    payload: dict[str, Any],
    status: int,
    code: str,
) -> None:
    ada = bearer(token_for(secured_api, "ada"))
    response = secured_api.post(f"{API}/admin/users", headers=ada, json=payload)
    assert response.status_code == status, response.text
    assert error_code(response) == code


def test_only_admins_manage_accounts(
    secured_api: TestClient, people: dict[str, User]
) -> None:
    for name in ("sam", "pia", "olga"):
        token = bearer(token_for(secured_api, name))
        for method, path in (
            ("POST", "/admin/users"),
            ("PATCH", f"/admin/users/{people['olga'].id}"),
            ("POST", f"/admin/users/{people['olga'].id}/status"),
            ("POST", f"/admin/users/{people['olga'].id}/reset-password"),
        ):
            response = secured_api.request(
                method, f"{API}{path}", headers=token,
                json={"username": "evil", "display_name": "E", "role": "admin", "is_active": False},
            )
            assert response.status_code == 403, (name, path)


def test_deactivation_ends_sessions_and_blocks_sign_in(
    secured_api: TestClient, people: dict[str, User], db_session: Session
) -> None:
    olga = bearer(token_for(secured_api, "olga"))
    ada = bearer(token_for(secured_api, "ada"))
    url = f"{API}/admin/users/{people['olga'].id}/status"
    off = secured_api.post(url, headers=ada, json={"is_active": False})
    assert off.status_code == 200 and off.json()["is_active"] is False
    assert secured_api.get(f"{API}/auth/me", headers=olga).status_code == 401
    assert login(secured_api, "olga").status_code == 401

    on = secured_api.post(url, headers=ada, json={"is_active": True})
    assert on.json()["is_active"] is True
    assert login(secured_api, "olga").status_code == 200
    assert {"user_deactivated", "user_reactivated"} <= set(audit_types(db_session))


def test_admins_cannot_lock_themselves_out(
    secured_api: TestClient, people: dict[str, User], db_session: Session
) -> None:
    ada = bearer(token_for(secured_api, "ada"))
    me = people["ada"].id
    deactivate = secured_api.post(
        f"{API}/admin/users/{me}/status", headers=ada, json={"is_active": False}
    )
    assert deactivate.status_code == 403 and error_code(deactivate) == "self_change_forbidden"
    demote = secured_api.patch(f"{API}/admin/users/{me}", headers=ada, json={"role": "operator"})
    assert demote.status_code == 403
    reset = secured_api.post(f"{API}/admin/users/{me}/reset-password", headers=ada)
    assert reset.status_code == 403

    # Defence in depth: the last active admin can never be demoted, whoever asks.
    from app.core.errors import ConflictError

    with pytest.raises(ConflictError):
        update_user(db_session, people["sam"], me, {"role": "operator"})


def test_role_changes_apply_immediately_and_clear_machine_scope(
    secured_api: TestClient, people: dict[str, User]
) -> None:
    olga = bearer(token_for(secured_api, "olga"))
    ada = bearer(token_for(secured_api, "ada"))
    assert secured_api.get(f"{API}/analytics/dashboard", headers=olga).status_code == 403
    response = secured_api.patch(
        f"{API}/admin/users/{people['olga'].id}", headers=ada, json={"role": "supervisor"}
    )
    assert response.status_code == 200
    assert response.json()["machine_ids"] == []
    assert secured_api.get(f"{API}/analytics/dashboard", headers=olga).status_code == 200


def test_password_reset_issues_a_one_time_password_and_ends_sessions(
    secured_api: TestClient, people: dict[str, User], db_session: Session
) -> None:
    olga = bearer(token_for(secured_api, "olga"))
    ada = bearer(token_for(secured_api, "ada"))
    response = secured_api.post(
        f"{API}/admin/users/{people['olga'].id}/reset-password", headers=ada
    )
    assert response.status_code == 200
    temporary = response.json()["temporary_password"]
    assert response.json()["user"]["must_change_password"] is True
    assert secured_api.get(f"{API}/auth/me", headers=olga).status_code == 401
    assert login(secured_api, "olga").status_code == 401
    assert login(secured_api, "olga", temporary).status_code == 200


def test_audit_log_records_access_events_without_secrets(
    secured_api: TestClient, people: dict[str, User], db_session: Session
) -> None:
    token = token_for(secured_api, "olga")
    login(secured_api, "olga", "wrong-password-123")
    ada_token = token_for(secured_api, "ada")
    reset = secured_api.post(
        f"{API}/admin/users/{people['olga'].id}/reset-password", headers=bearer(ada_token)
    ).json()
    response = secured_api.get(
        f"{API}/admin/audit-events", headers=bearer(ada_token), params={"limit": 200}
    )
    assert response.status_code == 200
    body = response.json()
    types = {event["event_type"] for event in body["items"]}
    assert {"user_created", "login_succeeded", "login_failed", "password_reset"} <= types
    dumped = json.dumps(body)
    for secret in (*PASSWORDS.values(), token, ada_token, reset["temporary_password"],
                   "wrong-password-123"):
        assert secret not in dumped
    only_failures = secured_api.get(
        f"{API}/admin/audit-events", headers=bearer(ada_token), params={"success": False}
    ).json()
    assert {event["event_type"] for event in only_failures["items"]} == {"login_failed"}


# --------------------------------------------------------------------------- workflow assistant


def _agent(app: FastAPI, replies: list[Any]) -> FakeAgent:
    fake = FakeAgent(replies)
    app.dependency_overrides[get_agent_model] = lambda: fake
    return fake


def test_assistant_roles_follow_the_account_role(
    secured_api: TestClient, people: dict[str, User]
) -> None:
    expected = {"olga": "operator", "sam": "supervisor", "pia": "viewer"}
    for name, role in expected.items():
        me = secured_api.get(f"{API}/workflows/me", headers=bearer(token_for(secured_api, name)))
        assert me.status_code == 200
        assert me.json()["name"] == name and me.json()["role"] == role
    admin = secured_api.get(f"{API}/workflows/me", headers=bearer(token_for(secured_api, "ada")))
    assert admin.status_code == 403
    assert WORKFLOW_ROLE[UserRole.PRODUCTION_MANAGER] is WorkflowRole.VIEWER


def test_operator_assistant_tools_are_limited_to_assigned_machines(
    app: FastAPI, secured_api: TestClient, people: dict[str, User]
) -> None:
    fake = _agent(app, [
        calls(
            ("get_machine_status", {}),
            ("query_downtime", {"date_from": "2026-01-01", "date_to": "2026-01-10",
                                "machine_code": "M2"}),
            ("query_downtime", {"date_from": "2026-01-01", "date_to": "2026-01-10"}),
        ),
        final("E1"),
    ])
    olga = bearer(token_for(secured_api, "olga"))
    response = secured_api.post(f"{API}/workflows", headers=olga, json={"question": "Status?"})
    assert response.status_code == 201, response.text
    steps = response.json()["steps"]
    assert [m["code"] for m in steps[0]["result"]["machines"]] == ["M1"]
    assert steps[1]["status"] == "rejected" and steps[1]["error_code"] == "machine_not_assigned"
    assert steps[2]["status"] == "rejected" and steps[2]["error_code"] == "machine_required"
    assert fake.payload(0)["PERSON_MACHINE_SCOPE"]["machine_codes"] == ["M1"]


def test_only_supervisors_approve_actions_prepared_by_operators(
    app: FastAPI, secured_api: TestClient, people: dict[str, User], db_session: Session
) -> None:
    _agent(app, [
        calls(("prepare_maintenance_request", {
            "machine_code": "M1", "issue_description": "Spindle vibration since morning",
            "priority": "high",
        })),
        final("E1"),
    ])
    olga = bearer(token_for(secured_api, "olga"))
    run = secured_api.post(
        f"{API}/workflows", headers=olga, json={"question": "Raise a request for M1"}
    )
    assert run.status_code == 201, run.text
    proposal = run.json()["proposal"]
    assert proposal["status"] == "pending_approval"
    payload = {"arguments_hash": proposal["arguments_hash"]}
    url = f"{API}/workflows/proposals/{proposal['id']}/approve"

    for name in ("olga", "pia"):
        refused = secured_api.post(
            url, headers=bearer(token_for(secured_api, name)),
            json={**payload, "idempotency_key": f"key-{name}-000000000"},
        )
        assert refused.status_code in (403, 404), (name, refused.text)
    admin = secured_api.post(
        url, headers=bearer(token_for(secured_api, "ada")),
        json={**payload, "idempotency_key": "key-ada-0000000000"},
    )
    assert admin.status_code == 403

    approved = secured_api.post(
        url, headers=bearer(token_for(secured_api, "sam")),
        json={**payload, "idempotency_key": "key-sam-0000000000"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "executed"
    assert approved.json()["approval"]["actor"] == "sam"


def test_operator_cannot_prepare_actions_for_other_machines(
    app: FastAPI, secured_api: TestClient, people: dict[str, User]
) -> None:
    _agent(app, [
        calls(("prepare_maintenance_request", {
            "machine_code": "M2", "issue_description": "Noise from the gearbox",
            "priority": "low",
        })),
        final(),
    ])
    olga = bearer(token_for(secured_api, "olga"))
    run = secured_api.post(f"{API}/workflows", headers=olga, json={"question": "Raise for M2"})
    assert run.status_code == 201
    assert run.json()["proposal"] is None
    assert run.json()["steps"][0]["error_code"] == "machine_not_assigned"


def test_assistant_requires_a_changed_password_too(
    secured_api: TestClient, plant: dict[str, Any], db_session: Session
) -> None:
    add_user(db_session, "sam", must_change=True)
    response = secured_api.get(
        f"{API}/workflows/me", headers=bearer(token_for(secured_api, "sam"))
    )
    assert response.status_code == 403
    assert error_code(response) == "password_change_required"


# --------------------------------------------------------------------------- legacy names


def test_usernames_cannot_reuse_legacy_workflow_token_names(
    app: FastAPI, secured_api: TestClient, people: dict[str, User]
) -> None:
    from app.core.security import hash_token

    app.state.settings = make_settings(
        workflow_access_tokens=f"carl:viewer:{hash_token('carl-viewer-token-0123456789')}"
    )
    ada = bearer(token_for(secured_api, "ada"))
    response = secured_api.post(
        f"{API}/admin/users", headers=ada,
        json={"username": "carl", "display_name": "Carl", "role": "supervisor"},
    )
    assert response.status_code == 409
    assert error_code(response) == "username_taken"


# --------------------------------------------------------------------------- admin-chosen passwords


def test_admin_can_choose_the_password_and_skip_the_forced_change(
    secured_api: TestClient, people: dict[str, User], plant: dict[str, Any], db_session: Session
) -> None:
    ada = bearer(token_for(secured_api, "ada"))
    response = secured_api.post(
        f"{API}/admin/users", headers=ada,
        json={"username": "otto", "display_name": "Otto", "role": "operator",
              "machine_ids": [plant["m1"]], "temporary_password": "Easy-floor-2026",
              "require_password_change": False},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["temporary_password"] is None  # the admin already knows it; never echoed
    assert body["user"]["must_change_password"] is False
    assert "Easy-floor-2026" not in json.dumps(body)
    signed_in = login(secured_api, "otto", "Easy-floor-2026")
    assert signed_in.status_code == 200
    token = signed_in.json()["access_token"]
    # Straight to work: no password change step.
    assert secured_api.get(f"{API}/machines", headers=bearer(token)).status_code == 200
    created = db_session.scalar(
        select(AuthAuditEvent).where(AuthAuditEvent.event_type == "user_created")
        .order_by(AuthAuditEvent.id.desc())
    )
    assert created is not None and created.details["password"] == "chosen_by_admin"  # noqa: S105
    assert "Easy-floor-2026" not in json.dumps(created.details)


def test_admin_chosen_password_can_still_require_a_change(
    secured_api: TestClient, people: dict[str, User]
) -> None:
    ada = bearer(token_for(secured_api, "ada"))
    response = secured_api.post(
        f"{API}/admin/users", headers=ada,
        json={"username": "otto", "display_name": "Otto", "role": "supervisor",
              "temporary_password": "Easy-floor-2026"},  # require_password_change defaults to true
    )
    assert response.status_code == 201
    assert response.json()["user"]["must_change_password"] is True
    token = login(secured_api, "otto", "Easy-floor-2026").json()["access_token"]
    blocked = secured_api.get(f"{API}/analytics/dashboard", headers=bearer(token))
    assert error_code(blocked) == "password_change_required"


def test_a_generated_password_always_requires_a_change(
    secured_api: TestClient, people: dict[str, User]
) -> None:
    ada = bearer(token_for(secured_api, "ada"))
    response = secured_api.post(
        f"{API}/admin/users", headers=ada,
        json={"username": "otto", "display_name": "Otto", "role": "supervisor",
              "require_password_change": False},
    )
    assert response.status_code == 201
    assert response.json()["temporary_password"]
    assert response.json()["user"]["must_change_password"] is True


def test_admin_can_reset_to_a_password_they_choose(
    secured_api: TestClient, people: dict[str, User]
) -> None:
    olga = bearer(token_for(secured_api, "olga"))
    ada = bearer(token_for(secured_api, "ada"))
    url = f"{API}/admin/users/{people['olga'].id}/reset-password"
    weak = secured_api.post(url, headers=ada, json={"new_password": "short"})
    assert weak.status_code == 422 and error_code(weak) == "weak_password"
    response = secured_api.post(
        url, headers=ada,
        json={"new_password": "Floor-new-pass-77", "require_password_change": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["temporary_password"] is None
    assert response.json()["user"]["must_change_password"] is False
    assert secured_api.get(f"{API}/auth/me", headers=olga).status_code == 401  # sessions ended
    assert login(secured_api, "olga").status_code == 401
    assert login(secured_api, "olga", "Floor-new-pass-77").status_code == 200