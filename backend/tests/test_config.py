from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.db.session import redacted_database_url
from tests.conftest import make_settings


def test_plain_postgresql_url_is_normalised_to_psycopg_driver() -> None:
    s = make_settings(database_url="postgresql://u:p@db:5432/foundryos")
    assert s.database_url == "postgresql+psycopg://u:p@db:5432/foundryos"


def test_non_postgresql_url_is_rejected() -> None:
    with pytest.raises(ValidationError, match="PostgreSQL"):
        make_settings(database_url="sqlite:///local.db")


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_database_url_is_hidden_from_repr() -> None:
    assert "test-password" not in repr(make_settings())


def test_cors_origins_parsed_from_comma_separated_string() -> None:
    s = make_settings(cors_allowed_origins=" http://a.test , http://b.test ,")
    assert s.cors_origins == ["http://a.test", "http://b.test"]


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="wildcard"):
        make_settings(environment="production", cors_allowed_origins="*")


def test_production_requires_https_origins() -> None:
    with pytest.raises(ValidationError, match="https"):
        make_settings(environment="production", cors_allowed_origins="http://foundryos.example")


def test_production_accepts_explicit_https_origins() -> None:
    s = make_settings(environment="production", cors_allowed_origins="https://foundryos.example")
    assert s.is_production


def test_redacted_database_url_masks_password() -> None:
    redacted = redacted_database_url("postgresql+psycopg://user:hunter2@db:5432/foundryos")
    assert "hunter2" not in redacted
    assert "user" in redacted and "db:5432/foundryos" in redacted
