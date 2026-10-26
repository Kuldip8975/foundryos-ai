"""Response schemas for health endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CheckStatus = Literal["pass", "fail", "skip"]


class ComponentCheck(BaseModel):
    name: str = Field(description="Component being checked, e.g. 'database'.")
    status: CheckStatus
    latency_ms: float | None = Field(default=None, description="Time the check took.")
    detail: str | None = Field(default=None, description="Safe, human-readable explanation.")


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"
    service: str
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: list[ComponentCheck]
