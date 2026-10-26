"""Schemas for the workflow assistant (Module 4).

Four groups:
* request bodies sent by people (questions, approvals, rejections);
* tool arguments — every allowlisted tool has a strict model; arguments that
  do not validate are refused before any query runs;
* the agent turn the language model must return, validated strictly
  (unknown fields rejected, evidence ids checked against tool results);
* read models returned by the API.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.models.enums import (
    ApprovalDecision,
    DowntimeStatus,
    MaintenancePriority,
    MaintenanceStatus,
    ProposalStatus,
    WorkflowRole,
    WorkflowStatus,
    WorkflowStepStatus,
)
from app.schemas.common import Code, InputModel, ReadModel
from app.schemas.manufacturing import Shift

MAX_DOWNTIME_RANGE = timedelta(days=31)
MAX_METRICS_RANGE = timedelta(days=92)

# --------------------------------------------------------------------------- requests

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
ArgumentsHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
IdempotencyKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{16,64}$")]
DecisionNote = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


class WorkflowRunCreate(InputModel):
    question: Question


class ApprovalCreate(InputModel):
    """Approve exactly the action that was shown: ``arguments_hash`` must match."""

    arguments_hash: ArgumentsHash
    idempotency_key: IdempotencyKey = Field(
        description="Random key chosen by the client; resending it returns the same outcome"
    )
    note: DecisionNote | None = None


class RejectionCreate(InputModel):
    idempotency_key: IdempotencyKey
    note: DecisionNote | None = None


# --------------------------------------------------------------------------- tool arguments


class ToolArguments(BaseModel):
    """Base for tool arguments: unknown fields are refused, ints must be real ints."""

    model_config = ConfigDict(extra="forbid")


def _check_range(date_from: date, date_to: date, limit: timedelta) -> None:
    if date_to < date_from:
        raise ValueError("date_to must be on or after date_from")
    if date_to - date_from >= limit:
        raise ValueError(f"the date range can cover at most {limit.days} days")


class MachineStatusArgs(ToolArguments):
    machine_code: Code | None = None


class DowntimeArgs(ToolArguments):
    date_from: date
    date_to: date
    machine_code: Code | None = None
    status: DowntimeStatus | None = None
    utc_offset_minutes: int = Field(default=0, ge=-840, le=840, strict=True)

    @model_validator(mode="after")
    def _range(self) -> DowntimeArgs:
        _check_range(self.date_from, self.date_to, MAX_DOWNTIME_RANGE)
        return self


class ProductionQualityArgs(ToolArguments):
    date_from: date
    date_to: date
    machine_code: Code | None = None
    shift: Shift | None = None

    @model_validator(mode="after")
    def _range(self) -> ProductionQualityArgs:
        _check_range(self.date_from, self.date_to, MAX_METRICS_RANGE)
        return self


class MaintenanceListArgs(ToolArguments):
    machine_code: Code | None = None
    status: MaintenanceStatus | None = None
    priority: MaintenancePriority | None = None
    limit: int = Field(default=10, ge=1, le=20, strict=True)


IssueDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)
]


class PrepareMaintenanceArgs(ToolArguments):
    """Prepares — never creates — a maintenance request. A person must approve it."""

    machine_code: Code
    issue_description: IssueDescription
    priority: MaintenancePriority


# --------------------------------------------------------------------------- model output

EvidenceId = Annotated[str, StringConstraints(pattern=r"^E[0-9]{1,2}$")]
ToolName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolCall(_Strict):
    # A plain string on purpose: an unknown tool is recorded and refused by the
    # allowlist rather than failing the whole turn.
    tool: ToolName
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallsTurn(_Strict):
    type: Literal["tool_calls"]
    calls: Annotated[list[ToolCall], Field(min_length=1, max_length=4)]


class AnswerFinding(_Strict):
    statement: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)
    ]
    evidence: Annotated[list[EvidenceId], Field(min_length=1, max_length=6)]

    @field_validator("evidence")
    @classmethod
    def _evidence_exists(cls, value: list[str], info: ValidationInfo) -> list[str]:
        allowed = (info.context or {}).get("allowed_evidence")
        if allowed is None:
            return value  # stored answers are re-read without context
        unknown = sorted(set(value) - set(allowed))
        if unknown:
            raise ValueError(f"evidence cites unknown tool results: {', '.join(unknown[:5])}")
        return value


Limitation = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class FinalTurn(_Strict):
    type: Literal["final"]
    answer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    findings: Annotated[list[AnswerFinding], Field(max_length=8)] = Field(default_factory=list)
    limitations: Annotated[list[Limitation], Field(max_length=5)] = Field(default_factory=list)


AgentTurn = Annotated[ToolCallsTurn | FinalTurn, Field(discriminator="type")]


class WorkflowAnswer(BaseModel):
    """A validated final answer as stored and returned."""

    answer: str
    findings: list[AnswerFinding]
    limitations: list[str]


# --------------------------------------------------------------------------- read models


class ActorRead(BaseModel):
    name: str
    role: WorkflowRole
    permissions: list[str]


class WorkflowStepRead(ReadModel):
    id: int
    sequence: int
    round: int
    tool: str
    arguments: dict[str, Any]
    status: WorkflowStepStatus
    evidence_id: str | None
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    duration_ms: int
    created_at: datetime


class ApprovalRead(ReadModel):
    decision: ApprovalDecision
    actor: str
    actor_role: WorkflowRole
    arguments_hash: str
    note: str | None
    created_at: datetime


class ProposalRead(ReadModel):
    id: int
    session_id: int
    action_type: str
    arguments: dict[str, Any]
    preview: dict[str, Any]
    arguments_hash: str = Field(description="Send this back to approve exactly this action")
    status: ProposalStatus
    proposed_by: str
    expires_at: datetime
    result: dict[str, Any] | None
    result_record_type: str | None
    result_record_id: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    decided_at: datetime | None
    executed_at: datetime | None
    approval: ApprovalRead | None


class AuditEventRead(ReadModel):
    id: int
    proposal_id: int | None
    event_type: str
    actor: str
    details: dict[str, Any]
    created_at: datetime


class WorkflowSessionSummary(ReadModel):
    id: int
    actor: str
    actor_role: WorkflowRole
    question: str
    status: WorkflowStatus
    tool_call_count: int
    includes_synthetic_data: bool
    proposal_status: ProposalStatus | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class WorkflowSessionRead(WorkflowSessionSummary):
    provider: str | None
    model: str | None
    prompt_version: str
    answer: WorkflowAnswer | None
    steps: list[WorkflowStepRead]
    proposal: ProposalRead | None
    audit_events: list[AuditEventRead]