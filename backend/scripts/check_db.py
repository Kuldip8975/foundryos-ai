"""Read-only PostgreSQL connectivity and privilege check for local setup.

Usage (from the backend/ directory, virtualenv active):

    python scripts/check_db.py                 # checks DATABASE_URL
    python scripts/check_db.py --target test   # checks TEST_DATABASE_URL

URLs are read the same way the application reads settings: real environment
variables first, then ``.env`` in the current directory, then ``../.env``.

Guarantees:
* never prints credentials: every URL shown is passed through ``redact_url``,
  which masks the password in the authority (``user:PASSWORD@host``) and the
  value of every credential-like query parameter (``?password=...``,
  ``sslpassword``, ...); error messages are scrubbed of those values too;
* the session is opened with ``default_transaction_read_only=on`` and only
  runs SELECT statements: it creates, alters, migrates or deletes nothing;
* it never prompts for a password. Supply it via the libpq password file
  (recommended), the PGPASSWORD environment variable, or the URL itself.

Exit codes: 0 ok · 1 connection/auth failure · 2 configuration error ·
3 connected, but the role cannot create tables in schema "public"
(``alembic upgrade head`` would fail).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from urllib.parse import unquote, urlsplit

# SQLAlchemy and pydantic-settings are imported inside the functions that use
# them, so the redaction helpers below depend only on the standard library.

EXIT_OK, EXIT_CONNECT, EXIT_CONFIG, EXIT_PRIVILEGES = 0, 1, 2, 3
_SUPPORTED_PREFIX = "postgresql+psycopg://"

REDACTED = "***"
UNPARSEABLE_URL = "<database URL redacted: could not be parsed>"
# Query-parameter names whose values are treated as secrets (case-insensitive,
# substring match): password, sslpassword, passwd, pwd, secret, token, ...
_SENSITIVE_QUERY_KEY = re.compile(r"pass|pwd|secret|token", re.IGNORECASE)
# Anything that looks like "<scheme>://..." inside free text (error messages).
_URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^\s'\"<>]+")


def _split_userinfo(netloc: str) -> tuple[str | None, str]:
    """Split ``user:pass@host`` at the LAST '@' (userinfo may contain '@')."""
    if "@" not in netloc:
        return None, netloc
    userinfo, _, hostinfo = netloc.rpartition("@")
    return userinfo, hostinfo


def redact_url(url: str) -> str:
    """Return ``url`` with every credential masked; safe to print or log.

    Masks the authority password (``user:PASSWORD@host``) and the value of
    every credential-like query parameter. The fragment is dropped. Anything
    that cannot be parsed is replaced entirely rather than shown.
    """
    try:
        parts = urlsplit(url.strip())
        if not parts.scheme or not parts.netloc:
            return UNPARSEABLE_URL
        userinfo, hostinfo = _split_userinfo(parts.netloc)
        if userinfo is None:
            netloc = hostinfo
        elif ":" in userinfo:
            netloc = f"{userinfo.split(':', 1)[0]}:{REDACTED}@{hostinfo}"
        else:
            netloc = f"{userinfo}@{hostinfo}"

        query_items = []
        for item in parts.query.split("&") if parts.query else []:
            key, sep, _value = item.partition("=")
            if _SENSITIVE_QUERY_KEY.search(unquote(key)):
                query_items.append(f"{key}={REDACTED}")
            else:
                query_items.append(item if sep else key)
        query = f"?{'&'.join(query_items)}" if query_items else ""
        return f"{parts.scheme}://{netloc}{parts.path}{query}"
    except Exception:  # never let a malformed URL leak through an error path
        return UNPARSEABLE_URL


def secret_values(url: str) -> set[str]:
    """All credential values carried by ``url`` (raw and percent-decoded)."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        # Unparseable here: callers also collect secrets from SQLAlchemy's own
        # parse (see run()), and redact_url() hides such URLs entirely.
        return set()
    found: set[str] = set()
    userinfo, _ = _split_userinfo(parts.netloc)
    if userinfo and ":" in userinfo:
        found.add(userinfo.split(":", 1)[1])
    for item in parts.query.split("&") if parts.query else []:
        key, _, value = item.partition("=")
        if _SENSITIVE_QUERY_KEY.search(unquote(key)):
            found.add(value)
    found |= {unquote(v) for v in found}
    return {v for v in found if v}


def scrub(message: str, secrets: set[str]) -> str:
    """Replace every secret value occurring in ``message`` (longest first)."""
    for secret in sorted(secrets, key=len, reverse=True):
        message = message.replace(secret, REDACTED)
    return message


def _safe_error_message(exc: BaseException, secrets: set[str]) -> str:
    """First line of the driver's error (or the exception itself), with secrets removed.

    Also redacts anything URL-shaped in the message, in case a library echoes
    a connection string containing credentials we did not know about.
    """
    lines = str(getattr(exc, "orig", None) or exc).strip().splitlines()
    message = lines[0] if lines else type(exc).__name__
    message = scrub(message, secrets)
    return _URL_IN_TEXT.sub(lambda m: redact_url(m.group(0)), message)


def _has_url_password(url: str) -> bool:
    return bool(secret_values(url))


def _load_urls() -> tuple[str | None, str | None]:
    """Read the two URLs with the same sources as app.core.config.Settings."""
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class _ConnectionUrls(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
        )
        database_url: str | None = None
        test_database_url: str | None = None

    urls = _ConnectionUrls()
    return urls.database_url, urls.test_database_url


def _fail(code: int, message: str) -> int:
    print(f"FAIL  {message}")
    return code


def run(target: str) -> int:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError, SQLAlchemyError
    from sqlalchemy.pool import NullPool

    database_url, test_database_url = _load_urls()
    var = "TEST_DATABASE_URL" if target == "test" else "DATABASE_URL"
    url = test_database_url if target == "test" else database_url

    if not url:
        return _fail(EXIT_CONFIG, f"{var} is not set (environment or .env).")
    url = url.strip()
    if not url.startswith(_SUPPORTED_PREFIX):
        return _fail(EXIT_CONFIG, f"{var} must start with {_SUPPORTED_PREFIX}")
    try:
        parsed = make_url(url)
    except ArgumentError:
        return _fail(EXIT_CONFIG, f"{var} is not a valid URL.")
    if not parsed.database or not parsed.username:
        return _fail(EXIT_CONFIG, f"{var} must include a user name and a database name.")

    if target == "test":
        if not parsed.database.endswith("_test"):
            return _fail(EXIT_CONFIG, "TEST_DATABASE_URL database name must end with '_test'.")
        try:
            app_db = make_url(database_url.strip()).database if database_url else None
        except ArgumentError:
            app_db = None
        if app_db == parsed.database:
            return _fail(
                EXIT_CONFIG, "TEST_DATABASE_URL must not target the DATABASE_URL database."
            )

    # Secrets to scrub from any error output: from our own parse, from
    # SQLAlchemy's parse (in case the two parsers disagree), and PGPASSWORD.
    secrets = secret_values(url)
    if parsed.password:
        secrets.add(str(parsed.password))
    for key, value in parsed.query.items():
        if _SENSITIVE_QUERY_KEY.search(key):
            secrets.update(v for v in ([value] if isinstance(value, str) else value) if v)
    if os.environ.get("PGPASSWORD"):
        secrets.add(os.environ["PGPASSWORD"])

    if _has_url_password(url) or parsed.password:
        auth_source = "embedded in URL"
    elif os.environ.get("PGPASSWORD"):
        auth_source = "PGPASSWORD environment variable"
    else:
        auth_source = "libpq password file (PGPASSFILE / pgpass.conf / ~/.pgpass)"

    print(f"Target         : {var}")
    print(f"URL            : {redact_url(url)}")
    print(f"Password source: {auth_source}")

    engine = None
    try:
        engine = create_engine(
            url,
            poolclass=NullPool,
            connect_args={
                "connect_timeout": 5,
                "application_name": "foundryos-check-db",
                "options": "-c default_transaction_read_only=on",
            },
        )
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT current_user,
                           current_database(),
                           current_setting('server_version'),
                           current_setting('default_transaction_read_only'),
                           has_database_privilege(current_database(), 'CONNECT'),
                           has_database_privilege(current_database(), 'CREATE'),
                           has_schema_privilege('public', 'USAGE'),
                           has_schema_privilege('public', 'CREATE'),
                           to_regclass('public.alembic_version') IS NOT NULL
                    """
                )
            ).one()
            revisions: list[str] = []
            if row[8]:
                revisions = [
                    r[0] for r in conn.execute(text("SELECT version_num FROM alembic_version"))
                ]
    except SQLAlchemyError as exc:
        return _fail(EXIT_CONNECT, f"could not connect: {_safe_error_message(exc, secrets)}")
    except Exception as exc:  # any driver/runtime error: still never show raw text
        return _fail(
            EXIT_CONNECT,
            f"could not connect ({type(exc).__name__}): {_safe_error_message(exc, secrets)}",
        )
    finally:
        if engine is not None:
            engine.dispose()

    (user, database, version, read_only, db_connect, db_create,
     schema_usage, schema_create, has_alembic) = row
    print(f"Connected as   : {user} -> database {database} (PostgreSQL {version})")
    print(f"Read-only sess.: {read_only}")
    print(f"DB  CONNECT    : {db_connect}")
    print(f"DB  CREATE     : {db_create}")
    print(f"public USAGE   : {schema_usage}")
    print(f"public CREATE  : {schema_create}")
    print(
        "Migrations     : "
        + (f"applied, revision {revisions}" if has_alembic else "not applied (no alembic_version)")
    )

    if not (schema_usage and schema_create):
        return _fail(
            EXIT_PRIVILEGES,
            f'role "{user}" cannot create tables in schema "public" of "{database}"; '
            "`alembic upgrade head` would fail. See docs/local-database-setup.md, Step 5.",
        )
    print("OK    connection verified (read-only check; nothing was changed)")
    return EXIT_OK


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", choices=["app", "test"], default="app")
    sys.exit(run(parser.parse_args().target))


if __name__ == "__main__":
    main()