"""TEST_DATABASE_URL safety gate (tests/db_target_guard.py).

None of these tests opens a connection. The last group proves the integration
module's own gate rejects unsafe targets before any engine or migration call.
"""

from __future__ import annotations

import inspect

import pytest

from tests.db_target_guard import (
    TestDatabaseTarget,
    UnsafeTestDatabaseError,
    validate_test_database_url,
)

# --- accepted: local, psycopg driver, *_test database ------------------------

@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "postgresql+psycopg://foundryos_app@127.0.0.1:5432/foundryos_test",
            TestDatabaseTarget("127.0.0.1", 5432, "foundryos_test"),
        ),
        (
            "postgresql+psycopg://foundryos_app:pw@localhost:5432/foundryos_test",
            TestDatabaseTarget("localhost", 5432, "foundryos_test"),
        ),
        (
            "postgresql+psycopg://foundryos_app@[::1]:5432/foundryos_test",
            TestDatabaseTarget("::1", 5432, "foundryos_test"),
        ),
        (
            "postgresql+psycopg://foundryos_app@LOCALHOST/foundryos_test",
            TestDatabaseTarget("localhost", None, "foundryos_test"),
        ),
        (
            "postgresql+psycopg://u@127.0.0.1:5433/other_test?sslmode=disable&connect_timeout=3",
            TestDatabaseTarget("127.0.0.1", 5433, "other_test"),
        ),
        (
            "  postgresql+psycopg://u@localhost/foundryos_test  ",  # surrounding spaces trimmed
            TestDatabaseTarget("localhost", None, "foundryos_test"),
        ),
    ],
)
def test_accepts_local_test_databases(url: str, expected: TestDatabaseTarget) -> None:
    assert validate_test_database_url(url) == expected


# --- rejected: remote or ambiguous hosts -------------------------------------

@pytest.mark.parametrize(
    "hostinfo",
    [
        "db.example.com:5432",
        "prod-db:5432",
        "10.0.0.5:5432",
        "192.168.1.20",
        "172.17.0.1:5432",
        "8.8.8.8",
        "0.0.0.0:5432",
        "127.0.0.2:5432",           # only the exact loopback addresses are allowed
        "[2001:db8::1]:5432",
        "[::ffff:10.0.0.5]:5432",
        "localhost.example.com",
        "127.0.0.1.nip.io",
        "localhost,db.example.com",  # libpq multi-host
        "localhost:5432,10.0.0.5:5432",
        "localhost@db.example.com",  # userinfo trick: the real host is after the last '@'
    ],
)
def test_rejects_remote_hosts(hostinfo: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError):
        validate_test_database_url(f"postgresql+psycopg://u:RemotePw1@{hostinfo}/foundryos_test")


@pytest.mark.parametrize(
    "query",
    [
        "host=db.example.com",
        "HOST=db.example.com",
        "h%6Fst=db.example.com",    # percent-encoded key
        "hostaddr=10.0.0.5",
        "port=6543",
        "dbname=foundryos",          # would bypass the _test name check
        "service=prod",
        "servicefile=/tmp/pg_service.conf",
        "sslmode=require&host=db.example.com",
    ],
)
def test_rejects_query_parameters_that_override_the_target(query: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError, match="query string"):
        validate_test_database_url(f"postgresql+psycopg://u@127.0.0.1:5432/foundryos_test?{query}")


# --- rejected: driver, database name, malformed/unsafe URLs ------------------

@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u@127.0.0.1/foundryos_test",
        "postgres://u@127.0.0.1/foundryos_test",
        "postgresql+psycopg2://u@127.0.0.1/foundryos_test",
        "sqlite:///foundryos_test",
    ],
)
def test_rejects_other_drivers(url: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError, match="driver prefix"):
        validate_test_database_url(url)


@pytest.mark.parametrize(
    "database",
    ["foundryos", "", "test", "foundryos_test_copy", "a/b_test", "foundry-os_test", "x%20y_test"],
)
def test_rejects_non_test_database_names(database: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError, match="_test"):
        validate_test_database_url(f"postgresql+psycopg://u@127.0.0.1:5432/{database}")


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "   ",
        "postgresql+psycopg:///foundryos_test",                      # no host (Unix socket)
        "postgresql+psycopg://u@127.0.0.1:0/foundryos_test",
        "postgresql+psycopg://u@127.0.0.1:70000/foundryos_test",
        "postgresql+psycopg://u@127.0.0.1:abc/foundryos_test",
        "postgresql+psycopg://u@[::1/foundryos_test",                # malformed IPv6
        "postgresql+psycopg://u@[::1]x/foundryos_test",
        "postgresql+psycopg://u@127.0.0.1/foundryos_test#frag",
        "postgresql+psycopg://u@127.0.0.1/found\tryos_test",        # embedded control character
        "postgresql+psycopg://u@local host/foundryos_test",          # embedded whitespace
    ],
)
def test_rejects_malformed_or_unsafe_urls(url: str | None) -> None:
    with pytest.raises(UnsafeTestDatabaseError):
        validate_test_database_url(url)


def test_error_messages_never_contain_credentials() -> None:
    with pytest.raises(UnsafeTestDatabaseError) as excinfo:
        validate_test_database_url("postgresql+psycopg://admin:Sup3rS3cret@db.example.com/prod_test")
    assert "Sup3rS3cret" not in str(excinfo.value)
    assert "db.example.com" not in str(excinfo.value)


# --- the integration module's gate runs before any connection/migration ------

def _integration_module_with_tripwires(monkeypatch: pytest.MonkeyPatch) -> tuple[object, list[str]]:
    """Import the integration test module with create_engine/upgrade replaced by tripwires."""
    from tests import test_db_integration as integration

    calls: list[str] = []

    def tripwire(name: str):
        def _called(*args: object, **kwargs: object) -> None:
            calls.append(name)
            raise AssertionError(f"{name} must not be called for an unsafe target")
        return _called

    monkeypatch.setattr(integration, "create_engine", tripwire("create_engine"))
    monkeypatch.setattr(integration.command, "upgrade", tripwire("alembic upgrade"))
    return integration, calls


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://foundryos_app:pw@db.example.com:5432/foundryos_test",
        "postgresql+psycopg://foundryos_app@10.0.0.5:5432/foundryos_test",
        "postgresql+psycopg://foundryos_app@127.0.0.1:5432/foundryos_test?host=db.example.com",
        "postgresql+psycopg://foundryos_app@127.0.0.1:5432/foundryos",
    ],
)
def test_integration_gate_rejects_unsafe_target_before_connecting(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    integration, calls = _integration_module_with_tripwires(monkeypatch)
    with pytest.raises(pytest.fail.Exception, match="Refusing to run integration tests"):
        integration.require_safe_test_database_url(url)  # type: ignore[attr-defined]
    assert calls == []


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://foundryos_app@127.0.0.1:5432/foundryos_test",
        "postgresql+psycopg://foundryos_app@localhost:5432/foundryos_test",
        "postgresql+psycopg://foundryos_app@[::1]:5432/foundryos_test",
    ],
)
def test_integration_gate_accepts_local_test_database_without_connecting(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    integration, calls = _integration_module_with_tripwires(monkeypatch)
    assert integration.require_safe_test_database_url(url) == url  # type: ignore[attr-defined]
    assert calls == []


def test_every_integration_test_receives_the_url_only_through_the_gated_fixture() -> None:
    from tests import test_db_integration as integration

    tests = [
        obj for name, obj in vars(integration).items()
        if name.startswith("test_") and inspect.isfunction(obj)
    ]
    assert tests, "expected integration tests to exist"
    for fn in tests:
        assert "integration_db_url" in inspect.signature(fn).parameters, fn.__name__
    assert "TEST_DATABASE_URL" not in inspect.getsource(
        integration.test_postgresql_connectivity  # type: ignore[attr-defined]
    )