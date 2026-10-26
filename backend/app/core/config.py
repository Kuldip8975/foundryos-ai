"""Central application configuration.

All settings come from environment variables (optionally loaded from a local,
git-ignored ``.env`` file). Nothing secret has a default value: the application
refuses to start if ``DATABASE_URL`` is missing.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.security import AccessEntry, parse_access_entries

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

_SUPPORTED_DB_PREFIX = "postgresql+psycopg://"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Looks for .env in the current directory first, then the repo root
        # (when running from backend/). Real environment variables win.
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "FoundryOS AI"
    app_version: str = "0.1.0"
    environment: Environment = "development"

    log_level: LogLevel = "INFO"
    log_format: Literal["json", "console"] = "json"

    api_v1_prefix: str = "/api/v1"
    enable_api_docs: bool = True

    # Required. Example: postgresql+psycopg://user:password@localhost:5432/foundryos
    database_url: str = Field(..., repr=False)
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_timeout_seconds: int = Field(default=30, ge=1, le=300)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)

    # Comma-separated list of allowed browser origins, e.g.
    # "http://localhost:5173,https://foundryos.example.com"
    cors_allowed_origins: str = "http://localhost:5173"

    # AI shift reports (Module 3). Disabled unless explicitly enabled: turning it
    # on sends aggregated shift metrics (totals, ratios, machine/defect codes and
    # short downtime reasons; never notes or ids) to Google's Gemini API.
    # See docs/module-3-shift-reports.md for exactly what is sent.
    ai_reports_enabled: bool = False
    gemini_api_key: SecretStr | None = Field(default=None, repr=False)
    gemini_model: str = Field(
        default="gemini-flash-latest", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
    )
    # Empty = the model's default amount of "thinking". "low" or "minimal" makes
    # reports much faster; only models that support thinking levels accept it.
    gemini_thinking_level: Literal["", "minimal", "low", "medium", "high"] = ""
    ai_request_timeout_seconds: float = Field(default=60, ge=1, le=120)

    # Workflow assistant (Module 4). Off unless enabled AND a Gemini key is set.
    # Only aggregated figures, machine codes/names, short downtime reasons and
    # short maintenance issue descriptions are sent to the model (see
    # docs/module-4-workflow-agent.md).
    ai_workflow_enabled: bool = False
    # Who may use the assistant: comma-separated "name:role:sha256-of-token"
    # entries (roles: viewer, operator, supervisor). Generate entries with
    #   python -m app.cli.workflow_token <name> <role>
    # Only token hashes are stored here; the tokens themselves are never stored.
    workflow_access_tokens: SecretStr | None = Field(default=None, repr=False)
    # Separation of duties: the person who prepared an action cannot approve it.
    workflow_require_distinct_approver: bool = True
    workflow_proposal_ttl_minutes: int = Field(default=15, ge=1, le=1440)
    workflow_max_tool_calls: int = Field(default=8, ge=1, le=20)
    workflow_max_rounds: int = Field(default=4, ge=2, le=8)
    # Whole-run budget. Kept below the browser's 180 s wait so the UI always
    # receives the server's answer.
    workflow_timeout_seconds: float = Field(default=120, ge=20, le=160)

    # Sign-in and sessions (Module 5). Accounts are created only by an admin
    # (or the one-time bootstrap command: python -m app.cli.create_admin).
    # A session ends after this absolute lifetime (default: one 8-hour shift)...
    auth_session_ttl_minutes: int = Field(default=480, ge=15, le=1440)
    # ...or after this much inactivity, whichever comes first.
    auth_idle_timeout_minutes: int = Field(default=30, ge=5, le=480)
    # Failed sign-ins before an account is locked, and for how long.
    auth_max_failed_logins: int = Field(default=5, ge=3, le=20)
    auth_lockout_minutes: int = Field(default=15, ge=1, le=1440)
    # Sign-in attempts allowed per client address and per username within the
    # window (in-memory, per server process; the account lockout above is
    # stored in the database and applies across processes).
    auth_rate_limit_attempts: int = Field(default=10, ge=3, le=1000)
    auth_rate_limit_window_seconds: int = Field(default=300, ge=10, le=3600)
    # Public demo deployment: the shared demo accounts (python -m app.cli.demo_accounts)
    # cannot change their password, so every visitor can sign in with the published one.
    demo_mode: bool = False

    @field_validator("database_url")
    @classmethod
    def _normalise_database_url(cls, value: str) -> str:
        value = value.strip()
        # Accept the common "postgresql://" / "postgres://" forms but always use
        # the psycopg (v3) driver explicitly.
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                value = _SUPPORTED_DB_PREFIX + value[len(prefix) :]
        if not value.startswith(_SUPPORTED_DB_PREFIX):
            raise ValueError(
                "DATABASE_URL must be a PostgreSQL URL "
                "(postgresql+psycopg://user:password@host:5432/dbname)"
            )
        return value

    @field_validator("workflow_access_tokens")
    @classmethod
    def _validate_workflow_tokens(cls, value: SecretStr | None) -> SecretStr | None:
        # Fail at startup on a malformed entry instead of at the first request.
        if value is not None:
            parse_access_entries(value.get_secret_value())
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def ai_configured(self) -> bool:
        """True when AI reports are enabled and an API key is present (never logs the key)."""
        key = self.gemini_api_key.get_secret_value().strip() if self.gemini_api_key else ""
        return self.ai_reports_enabled and bool(key)

    @property
    def workflow_ai_configured(self) -> bool:
        """True when the workflow assistant is enabled and a Gemini key is present."""
        key = self.gemini_api_key.get_secret_value().strip() if self.gemini_api_key else ""
        return self.ai_workflow_enabled and bool(key)

    @property
    def workflow_access_entries(self) -> tuple[AccessEntry, ...]:
        if self.workflow_access_tokens is None:
            return ()
        return parse_access_entries(self.workflow_access_tokens.get_secret_value())

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _validate_production_safety(self) -> Settings:
        if self.is_production:
            if "*" in self.cors_origins:
                raise ValueError(
                    "CORS_ALLOWED_ORIGINS must list explicit origins in production; "
                    "wildcard '*' is not allowed"
                )
            for origin in self.cors_origins:
                if not origin.startswith("https://"):
                    raise ValueError(
                        f"CORS origin {origin!r} must use https:// in production"
                    )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached)."""
    return Settings()  # type: ignore[call-arg]  # values come from the environment
