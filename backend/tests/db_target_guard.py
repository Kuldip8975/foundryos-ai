"""Safety gate for the database targeted by integration tests.

Integration tests run ``alembic upgrade head``, so the target must be a local,
disposable database. :func:`validate_test_database_url` is called before any
engine is created or migration is run, and rejects anything else.

Standard library only (no SQLAlchemy/psycopg), so it can be unit-tested
without a database driver and can never open a connection itself.
Error messages never include the URL or any part of its credentials.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

REQUIRED_SCHEME = "postgresql+psycopg"
ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# libpq connection parameters that, given in the query string, would override
# the host/port/database written in the URL (psycopg passes query parameters
# straight to libpq), or redirect the connection via a service definition.
FORBIDDEN_QUERY_KEYS = frozenset(
    {"host", "hostaddr", "port", "dbname", "service", "servicefile"}
)
_DATABASE_NAME = re.compile(r"^[A-Za-z0-9_]+_test$")


class UnsafeTestDatabaseError(ValueError):
    """TEST_DATABASE_URL does not point at a local, disposable test database."""


@dataclass(frozen=True)
class TestDatabaseTarget:
    __test__ = False  # not a pytest test class

    host: str
    port: int | None
    database: str


def _parse_host_port(hostinfo: str) -> tuple[str, int | None]:
    if not hostinfo:
        raise UnsafeTestDatabaseError("TEST_DATABASE_URL must name a host explicitly.")
    if "," in hostinfo:
        raise UnsafeTestDatabaseError("TEST_DATABASE_URL must name exactly one host.")
    if hostinfo.startswith("["):
        host, sep, rest = hostinfo[1:].partition("]")
        if not sep:
            raise UnsafeTestDatabaseError("TEST_DATABASE_URL has a malformed IPv6 host.")
        port_text = rest[1:] if rest.startswith(":") else None
        if rest and port_text is None:
            raise UnsafeTestDatabaseError("TEST_DATABASE_URL has a malformed host/port.")
    else:
        host, sep, port_text = hostinfo.partition(":")
        if not sep:
            port_text = None
    host = unquote(host).lower()

    port: int | None = None
    if port_text is not None:
        if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            raise UnsafeTestDatabaseError("TEST_DATABASE_URL has an invalid port.")
        port = int(port_text)
    return host, port


def validate_test_database_url(url: str | None) -> TestDatabaseTarget:
    """Accept only ``postgresql+psycopg://[user[:pw]@]LOCAL_HOST[:port]/<name>_test``.

    LOCAL_HOST is exactly one of ``localhost``, ``127.0.0.1`` or ``[::1]``.
    Raises :class:`UnsafeTestDatabaseError` for anything else.
    """
    if not url or not url.strip():
        raise UnsafeTestDatabaseError("TEST_DATABASE_URL is not set.")
    url = url.strip()
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise UnsafeTestDatabaseError(
            "TEST_DATABASE_URL contains whitespace or control characters."
        )

    try:
        parts = urlsplit(url)
    except ValueError:
        raise UnsafeTestDatabaseError("TEST_DATABASE_URL is not a valid URL.") from None

    if parts.scheme != REQUIRED_SCHEME:
        raise UnsafeTestDatabaseError(
            f"TEST_DATABASE_URL must use the {REQUIRED_SCHEME}:// driver prefix."
        )
    if parts.fragment:
        raise UnsafeTestDatabaseError("TEST_DATABASE_URL must not contain a '#' fragment.")

    # Split credentials at the LAST '@' so 'user@remote' tricks can't hide the host.
    hostinfo = parts.netloc.rpartition("@")[2]
    host, port = _parse_host_port(hostinfo)
    if host not in ALLOWED_HOSTS:
        raise UnsafeTestDatabaseError(
            "TEST_DATABASE_URL host must be localhost, 127.0.0.1 or [::1]; "
            "remote databases are never used for integration tests."
        )

    database = unquote(parts.path[1:]) if parts.path.startswith("/") else ""
    if not _DATABASE_NAME.match(database):
        raise UnsafeTestDatabaseError(
            "TEST_DATABASE_URL database name must end with '_test' and contain only "
            "letters, digits and underscores."
        )

    for item in parts.query.split("&") if parts.query else []:
        key = unquote(item.partition("=")[0]).strip().lower()
        if key in FORBIDDEN_QUERY_KEYS:
            raise UnsafeTestDatabaseError(
                f"TEST_DATABASE_URL must not set '{key}' in the query string "
                "(it would override the validated host or database)."
            )

    return TestDatabaseTarget(host=host, port=port, database=database)