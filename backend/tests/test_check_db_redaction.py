"""Credential redaction in scripts/check_db.py.

No test here opens a network or database connection: the end-to-end case
replaces ``sqlalchemy.create_engine`` with a fake that fails like a driver.
"""

from __future__ import annotations

import pytest

from scripts import check_db
from scripts.check_db import REDACTED, UNPARSEABLE_URL, redact_url, scrub, secret_values

AUTH_PW = "Auth%40Secret%3A1"          # percent-encoded form of 'Auth@Secret:1'
AUTH_PW_DECODED = "Auth@Secret:1"
QUERY_PW = "Query%26Secret%3D2"        # percent-encoded form of 'Query&Secret=2'
QUERY_PW_DECODED = "Query&Secret=2"


def _assert_no_secret(text: str, *secrets: str) -> None:
    for secret in secrets:
        assert secret not in text, "credential leaked into output"


# --- password in the authority (user:PASSWORD@host) -------------------------

def test_redacts_password_in_authority() -> None:
    url = f"postgresql+psycopg://foundryos_app:{AUTH_PW}@127.0.0.1:5432/foundryos"
    redacted = redact_url(url)
    assert redacted == f"postgresql+psycopg://foundryos_app:{REDACTED}@127.0.0.1:5432/foundryos"
    _assert_no_secret(redacted, AUTH_PW, AUTH_PW_DECODED)


def test_redacts_authority_password_containing_unencoded_at_sign() -> None:
    redacted = redact_url("postgresql+psycopg://user:p@ss@w0rd@localhost/foundryos")
    assert redacted == f"postgresql+psycopg://user:{REDACTED}@localhost/foundryos"
    _assert_no_secret(redacted, "p@ss@w0rd", "ss@w0rd")


def test_url_without_password_is_unchanged() -> None:
    url = "postgresql+psycopg://foundryos_app@127.0.0.1:5432/foundryos?sslmode=prefer"
    assert redact_url(url) == url
    assert secret_values(url) == set()


# --- password in the query string (?password=...) ---------------------------

def test_redacts_password_in_query_and_keeps_other_parameters() -> None:
    url = (
        "postgresql+psycopg://foundryos_app@127.0.0.1:5432/foundryos"
        f"?sslmode=require&password={QUERY_PW}&application_name=check"
    )
    redacted = redact_url(url)
    assert redacted == (
        "postgresql+psycopg://foundryos_app@127.0.0.1:5432/foundryos"
        f"?sslmode=require&password={REDACTED}&application_name=check"
    )
    _assert_no_secret(redacted, QUERY_PW, QUERY_PW_DECODED)


@pytest.mark.parametrize(
    "key", ["password", "PASSWORD", "sslpassword", "passwd", "pwd", "pass%77ord", "api_token"]
)
def test_redacts_credential_like_query_keys(key: str) -> None:
    redacted = redact_url(f"postgresql+psycopg://u@localhost/db?{key}=TopSecret9")
    assert "TopSecret9" not in redacted
    assert redacted.endswith(f"?{key}={REDACTED}")


def test_redacts_passwords_in_authority_and_query_together() -> None:
    url = f"postgresql+psycopg://u:{AUTH_PW}@localhost/db?password={QUERY_PW}"
    redacted = redact_url(url)
    assert redacted == f"postgresql+psycopg://u:{REDACTED}@localhost/db?password={REDACTED}"
    _assert_no_secret(redacted, AUTH_PW, AUTH_PW_DECODED, QUERY_PW, QUERY_PW_DECODED)


# --- malformed input and fragments ------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "not a url",
        "",
        "postgresql+psycopg://user:BadSecret@[::1/db",  # malformed IPv6 -> ValueError
    ],
)
def test_unparseable_urls_are_fully_replaced(url: str) -> None:
    redacted = redact_url(url)
    assert redacted == UNPARSEABLE_URL
    assert "BadSecret" not in redacted


def test_fragment_is_dropped() -> None:
    assert redact_url("postgresql+psycopg://u@localhost/db#FragSecret") == (
        "postgresql+psycopg://u@localhost/db"
    )


# --- scrubbing of error messages --------------------------------------------

def test_secret_values_include_raw_and_decoded_forms() -> None:
    url = f"postgresql+psycopg://u:{AUTH_PW}@localhost/db?password={QUERY_PW}"
    assert secret_values(url) == {AUTH_PW, AUTH_PW_DECODED, QUERY_PW, QUERY_PW_DECODED}


def test_scrub_removes_every_secret_longest_first() -> None:
    message = "FATAL: auth failed (abcdef) [abc]"
    assert scrub(message, {"abc", "abcdef"}) == f"FATAL: auth failed ({REDACTED}) [{REDACTED}]"


# --- error-message sanitising ------------------------------------------------

def test_safe_error_message_redacts_urls_echoed_by_a_library() -> None:
    exc = RuntimeError("bad DSN postgresql+psycopg://admin:EchoedPw1@db.example.com/x?password=EchoedPw2")
    message = check_db._safe_error_message(exc, set())
    assert "EchoedPw1" not in message
    assert "EchoedPw2" not in message
    assert f"admin:{REDACTED}@db.example.com" in message


def test_safe_error_message_uses_first_line_only() -> None:
    exc = RuntimeError("first line\nsecond line with DETAIL")
    assert check_db._safe_error_message(exc, set()) == "first line"


# --- end to end: what check_db.run() prints ---------------------------------
# These replace sqlalchemy.create_engine with a fake; nothing touches the network.

URL_WITH_BOTH_PASSWORDS = (
    f"postgresql+psycopg://foundryos_app:{AUTH_PW}@127.0.0.1:5432/foundryos?password={QUERY_PW}"
)
ALL_SECRETS = (AUTH_PW, AUTH_PW_DECODED, QUERY_PW, QUERY_PW_DECODED)
ECHOED = f"{AUTH_PW_DECODED} / {QUERY_PW_DECODED} / {AUTH_PW}"


def _run_with_fake_engine(monkeypatch: pytest.MonkeyPatch, create_engine_fake) -> int:
    import sqlalchemy

    monkeypatch.setattr(check_db, "_load_urls", lambda: (URL_WITH_BOTH_PASSWORDS, None))
    monkeypatch.setattr(sqlalchemy, "create_engine", create_engine_fake)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    return check_db.run("app")


def _engine_whose_connect_raises(exc: BaseException):
    class FailingEngine:
        disposed = False

        def connect(self) -> None:
            raise exc

        def dispose(self) -> None:
            FailingEngine.disposed = True

    return FailingEngine


def test_run_redacts_url_and_driver_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Driver error deliberately echoes both passwords (worst case)."""
    from sqlalchemy.exc import OperationalError

    engine_cls = _engine_whose_connect_raises(
        OperationalError("SELECT 1", {}, Exception(f"auth failed: {ECHOED}"))
    )
    exit_code = _run_with_fake_engine(monkeypatch, lambda *a, **k: engine_cls())
    out = capsys.readouterr().out

    assert exit_code == check_db.EXIT_CONNECT
    assert f"foundryos_app:{REDACTED}@127.0.0.1:5432/foundryos?password={REDACTED}" in out
    assert "could not connect" in out
    assert engine_cls.disposed
    _assert_no_secret(out, *ALL_SECRETS)


def test_run_sanitises_non_sqlalchemy_driver_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    engine_cls = _engine_whose_connect_raises(TypeError(f"unexpected argument {ECHOED}"))
    exit_code = _run_with_fake_engine(monkeypatch, lambda *a, **k: engine_cls())
    out = capsys.readouterr().out

    assert exit_code == check_db.EXIT_CONNECT
    assert "could not connect (TypeError)" in out
    _assert_no_secret(out, *ALL_SECRETS)


def test_run_sanitises_errors_raised_while_creating_the_engine(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing_create_engine(url: str, **kwargs: object) -> None:
        raise ValueError(f"cannot build engine for {url}")  # echoes the full URL

    exit_code = _run_with_fake_engine(monkeypatch, failing_create_engine)
    out = capsys.readouterr().out

    assert exit_code == check_db.EXIT_CONNECT
    assert "could not connect (ValueError)" in out
    _assert_no_secret(out, *ALL_SECRETS)


def test_run_scrubs_secrets_found_only_by_sqlalchemy_parsing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defence in depth: if our own parser found nothing, SQLAlchemy's parse still
    supplies the (decoded) authority and query passwords for scrubbing."""
    from sqlalchemy.exc import OperationalError

    monkeypatch.setattr(check_db, "secret_values", lambda url: set())
    engine_cls = _engine_whose_connect_raises(
        OperationalError(
            "SELECT 1", {}, Exception(f"auth failed: {AUTH_PW_DECODED} / {QUERY_PW_DECODED}")
        )
    )
    exit_code = _run_with_fake_engine(monkeypatch, lambda *a, **k: engine_cls())
    out = capsys.readouterr().out

    assert exit_code == check_db.EXIT_CONNECT
    assert "Password source: embedded in URL" in out
    _assert_no_secret(out, AUTH_PW_DECODED, QUERY_PW_DECODED)