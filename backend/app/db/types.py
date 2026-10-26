"""Shared column types.

* :class:`UTCDateTime` — every timestamp is stored and returned in UTC.
  Naive datetimes are rejected on write, so local times can never be stored
  ambiguously. PostgreSQL stores ``timestamptz``; SQLite (tests) stores the
  UTC wall time and UTC is re-attached on read.
* :data:`BigIntPK` — 64-bit keys on PostgreSQL; plain INTEGER on SQLite, where
  only ``INTEGER PRIMARY KEY`` autoincrements.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


def utcnow() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Naive datetime rejected: timestamps must be timezone-aware")
        value = value.astimezone(UTC)
        if dialect.name == "sqlite":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)