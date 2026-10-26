"""OpenAPI documentation for the standard error envelope."""

from typing import Any

from app.schemas.errors import ErrorResponse

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Not found"},
    409: {"model": ErrorResponse, "description": "Conflict (duplicate, overlap or status rule)"},
    422: {"model": ErrorResponse, "description": "Invalid input or business-rule violation"},
}