"""Workflow assistant persistence (Module 4).

    workflow_sessions ──< workflow_steps          (every tool call, allowed or refused)
            │      └──── action_proposals ──── action_approvals   (at most one decision)
            └──< workflow_audit_events >── action_proposals

Design rules:
* a session is one natural-language question answered by the agent;
* a proposal is a *prepared* change. It is only a row in this table until a
  human approves it; manufacturing tables are never written while planning;
* ``arguments_hash`` binds an approval to the exact action and arguments;
* ``action_approvals.proposal_id`` is unique, so a proposal can be decided
  once (replay protection), and ``idempotency_key`` is unique, so a retried
  approval request cannot execute twice;
* the maintenance request created on approval carries
  ``external_ref = "wf-proposal-<id>"`` (unique), a second guard against
  duplicate execution;
* audit events are append-only: no API updates or deletes them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import BigIntPK, UTCDateTime, utcnow
from app.models.enums import (
    ApprovalDecision,
    ProposalStatus,
    WorkflowRole,
    WorkflowStatus,
    WorkflowStepStatus,
    sql_in_list,
)
from app.models.reports import JsonDocument

ACTOR_LENGTH = 100
ROLE_LENGTH = 20
STATUS_LENGTH = 20
TOOL_LENGTH = 64
HASH_LENGTH = 64
ERROR_CODE_LENGTH = 50
ERROR_MESSAGE_LENGTH = 300


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, server_default=text("CURRENT_TIMESTAMP")
    )


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class WorkflowSession(Base):
    __tablename__ = "workflow_sessions"
    __table_args__ = (
        CheckConstraint(f"status IN ({sql_in_list(WorkflowStatus)})", name="status_valid"),
        CheckConstraint(f"actor_role IN ({sql_in_list(WorkflowRole)})", name="actor_role_valid"),
        CheckConstraint("status <> 'completed' OR answer IS NOT NULL", name="completed_has_answer"),
        CheckConstraint("tool_call_count >= 0", name="tool_call_count_non_negative"),
        Index("ix_workflow_sessions_actor_created", "actor", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    actor: Mapped[str] = mapped_column(String(ACTOR_LENGTH), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(ROLE_LENGTH), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False, index=True)
    answer: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    provider: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(30), nullable=False)
    tool_call_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    includes_synthetic_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    error_code: Mapped[str | None] = mapped_column(String(ERROR_CODE_LENGTH))
    error_message: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_LENGTH))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    steps: Mapped[list[WorkflowStep]] = relationship(
        back_populates="session", order_by="WorkflowStep.sequence"
    )
    proposal: Mapped[ActionProposal | None] = relationship(back_populates="session")
    audit_events: Mapped[list[WorkflowAuditEvent]] = relationship(
        back_populates="session", order_by="WorkflowAuditEvent.id"
    )

    @property
    def proposal_status(self) -> str | None:
        return self.proposal.status if self.proposal is not None else None


class WorkflowStep(Base):
    """One tool call requested by the model, whether it ran or was refused."""

    __tablename__ = "workflow_steps"
    __table_args__ = (
        CheckConstraint(f"status IN ({sql_in_list(WorkflowStepStatus)})", name="status_valid"),
        CheckConstraint(
            "(status = 'ok' AND evidence_id IS NOT NULL) "
            "OR (status <> 'ok' AND evidence_id IS NULL)",
            name="evidence_only_when_ok",
        ),
        UniqueConstraint("session_id", "sequence", name="uq_workflow_steps_session_sequence"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("workflow_sessions.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    tool: Mapped[str] = mapped_column(String(TOOL_LENGTH), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    status: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    evidence_id: Mapped[str | None] = mapped_column(String(10))
    result: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    error_code: Mapped[str | None] = mapped_column(String(ERROR_CODE_LENGTH))
    error_message: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_LENGTH))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _created_at()

    session: Mapped[WorkflowSession] = relationship(back_populates="steps")


class ActionProposal(Base):
    """A change prepared by the agent that only a human can approve."""

    __tablename__ = "action_proposals"
    __table_args__ = (
        CheckConstraint(f"status IN ({sql_in_list(ProposalStatus)})", name="status_valid"),
        CheckConstraint(
            "status <> 'executed' OR (result_record_id IS NOT NULL AND executed_at IS NOT NULL)",
            name="executed_has_record",
        ),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    # Unique: one proposal per session keeps every approval easy to review.
    session_id: Mapped[int] = mapped_column(
        BigIntPK,
        ForeignKey("workflow_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    action_type: Mapped[str] = mapped_column(String(TOOL_LENGTH), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    preview: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    arguments_hash: Mapped[str] = mapped_column(String(HASH_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False, index=True)
    proposed_by: Mapped[str] = mapped_column(String(ACTOR_LENGTH), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    result_record_type: Mapped[str | None] = mapped_column(String(50))
    result_record_id: Mapped[int | None] = mapped_column(BigIntPK)
    error_code: Mapped[str | None] = mapped_column(String(ERROR_CODE_LENGTH))
    error_message: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_LENGTH))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    session: Mapped[WorkflowSession] = relationship(back_populates="proposal")
    approval: Mapped[ActionApproval | None] = relationship(back_populates="proposal")


class ActionApproval(Base):
    """The single human decision on a proposal."""

    __tablename__ = "action_approvals"
    __table_args__ = (
        CheckConstraint(f"decision IN ({sql_in_list(ApprovalDecision)})", name="decision_valid"),
        CheckConstraint(f"actor_role IN ({sql_in_list(WorkflowRole)})", name="actor_role_valid"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        BigIntPK,
        ForeignKey("action_proposals.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    decision: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    actor: Mapped[str] = mapped_column(String(ACTOR_LENGTH), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(ROLE_LENGTH), nullable=False)
    arguments_hash: Mapped[str] = mapped_column(String(HASH_LENGTH), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created_at()

    proposal: Mapped[ActionProposal] = relationship(back_populates="approval")


class WorkflowAuditEvent(Base):
    """Append-only record of everything that happened in a workflow."""

    __tablename__ = "workflow_audit_events"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    session_id: Mapped[int | None] = mapped_column(
        BigIntPK, ForeignKey("workflow_sessions.id", ondelete="CASCADE"), index=True
    )
    proposal_id: Mapped[int | None] = mapped_column(
        BigIntPK, ForeignKey("action_proposals.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(ACTOR_LENGTH), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    created_at: Mapped[datetime] = _created_at()

    session: Mapped[WorkflowSession | None] = relationship(back_populates="audit_events")