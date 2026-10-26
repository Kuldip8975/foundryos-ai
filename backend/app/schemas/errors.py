"""Error envelope returned by every failing API request."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str = Field(description="Stable, machine-readable error code, e.g. 'not_found'.")
    message: str = Field(description="Human-readable summary safe to show to users.")
    details: list[dict[str, Any]] | None = Field(
        default=None, description="Optional structured details (e.g. validation errors)."
    )
    request_id: str | None = Field(
        default=None, description="Correlates the response with server logs."
    )


class ErrorResponse(BaseModel):
    error: ErrorDetail
