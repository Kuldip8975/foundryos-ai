"""Workflow history (Module 4). Supervisors see every session; others see their own."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models.enums import ProposalStatus, WorkflowStatus
from app.models.workflow import ActionProposal, WorkflowSession
from app.services.common import paginate
from app.services.workflow.approvals import expire_due_proposals
from app.services.workflow.permissions import Actor, Permission


@dataclass(frozen=True)
class SessionFilters:
    status: WorkflowStatus | None = None
    proposal_status: ProposalStatus | None = None


def list_sessions(
    db: Session,
    actor: Actor,
    filters: SessionFilters,
    *,
    limit: int,
    offset: int,
    now: datetime | None = None,
) -> tuple[list[WorkflowSession], int]:
    expire_due_proposals(db, now or datetime.now(UTC))
    stmt = select(WorkflowSession)
    if not actor.can(Permission.VIEW_ALL_SESSIONS):
        stmt = stmt.where(WorkflowSession.actor == actor.name)
    if filters.status is not None:
        stmt = stmt.where(WorkflowSession.status == filters.status.value)
    if filters.proposal_status is not None:
        stmt = stmt.join(ActionProposal, ActionProposal.session_id == WorkflowSession.id).where(
            ActionProposal.status == filters.proposal_status.value
        )
    order = (WorkflowSession.created_at.desc(), WorkflowSession.id.desc())
    return paginate(db, stmt, order_by=order, limit=limit, offset=offset)


def get_session(
    db: Session, session_id: int, actor: Actor, *, now: datetime | None = None
) -> WorkflowSession:
    expire_due_proposals(db, now or datetime.now(UTC))
    session = db.get(WorkflowSession, session_id)
    if session is None or (
        not actor.can(Permission.VIEW_ALL_SESSIONS) and session.actor != actor.name
    ):
        # Same answer for "missing" and "not yours".
        raise NotFoundError(f"Workflow session {session_id} was not found")
    return session