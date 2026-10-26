"""Schemas shared by all resource APIs."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

T = TypeVar("T")

# --- reusable field types ------------------------------------------------------

# Business identifiers: machine codes, part numbers, defect codes.
Code = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=50, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    ),
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)]
ExternalRef = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
# Strict: rejects "5", 5.0 and booleans; quantities are whole units.
Quantity = Annotated[int, Field(strict=True, ge=0, le=100_000_000)]
PositiveQuantity = Annotated[int, Field(strict=True, gt=0, le=100_000_000)]
EntityId = Annotated[int, Field(strict=True, gt=0, le=9_223_372_036_854_775_807)]


def _plain(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value.value if isinstance(value, Enum) else value for key, value in data.items()}


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def values(self) -> dict[str, Any]:
        """All fields, with enums converted to plain values (for the service layer)."""
        return _plain(self.model_dump())


class PatchModel(InputModel):
    """Partial update. Only fields present in the request are changed.

    Fields listed in ``non_nullable_fields`` may be omitted but never set to null.
    """

    non_nullable_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> PatchModel:
        nulls = sorted(
            name
            for name in self.non_nullable_fields
            if name in self.model_fields_set and getattr(self, name) is None
        )
        if nulls:
            raise ValueError(f"These fields cannot be null: {', '.join(nulls)}")
        return self

    def changes(self) -> dict[str, Any]:
        """Fields explicitly sent by the client, with enums converted to plain values."""
        return _plain(self.model_dump(exclude_unset=True))


class ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    """Paginated list response."""

    items: list[T]
    total: int = Field(description="Total rows matching the filters (ignores limit/offset).")
    limit: int
    offset: int