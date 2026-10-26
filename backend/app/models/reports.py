"""AI shift reports (Module 3).

Each row is one generation attempt. It stores the deterministic metrics
snapshot the report was generated from (``metrics``) and its SHA-256
fingerprint, so every statement in a report can be traced back to the exact
figures the model was given. Reports never modify manufacturing records.

At most one ``pending`` report may exist per request key (enforced by a
partial unique index), which prevents duplicate concurrent generations.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Date, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import BigIntPK, UTCDateTime, utcnow
from app.models.enums import DataSource, ReportStatus, sql_in_list

# JSONB on PostgreSQL (indexable, compact), generic JSON elsewhere (SQLite tests).
JsonDocument = JSON().with_variant(JSONB(), "postgresql")

REQUEST_KEY_LENGTH = 200


class ShiftReport(Base):
    __tablename__ = "shift_reports"
    __table_args__ = (
        CheckConstraint(f"status IN ({sql_in_list(ReportStatus)})", name="status_valid"),
        CheckConstraint(
            f"data_source IS NULL OR data_source IN ({sql_in_list(DataSource)})",
            name="data_source_valid",
        ),
        CheckConstraint(
            "(window_start IS NULL AND window_end IS NULL) OR "
            "(window_start IS NOT NULL AND window_end IS NOT NULL AND window_end > window_start)",
            name="window_valid",
        ),
        CheckConstraint(
            "status <> 'completed' OR content IS NOT NULL", name="completed_has_content"
        ),
        Index("ix_shift_reports_date_shift", "production_date", "shift"),
        Index(
            "uq_shift_reports_pending_request",
            "request_key",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    request_key: Mapped[str] = mapped_column(String(REQUEST_KEY_LENGTH), nullable=False)
    production_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift: Mapped[str] = mapped_column(String(16), nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(UTCDateTime())
    window_end: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # The data_source *filter* the report was requested with (null = all sources).
    data_source: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String(30), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    content: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    provider: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    @property
    def includes_synthetic_data(self) -> bool:
        """True when any record behind the metrics is synthetic demo data."""
        sources = (self.metrics or {}).get("data_sources") or {}
        return bool(sources.get(DataSource.SYNTHETIC.value))