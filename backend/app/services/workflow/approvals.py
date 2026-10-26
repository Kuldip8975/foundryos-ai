"""Human approval and execution of prepared actions (Module 4).

Approving runs these checks, in this order, before anything is written:

1. **Idempotency** — a repeated request with the same ``idempotency_key`` from
   the same person returns the recorded outcome and never executes twice; the
   key cannot be reused for a different proposal or decision.
2. **Authorisation** — the role must allow deciding actions, and (by default)
   the person who prepared the action cannot approve it.
3. **Expiry** — a proposal past ``expires_at`` is marked expired and refused.
4. **Replay** — only a ``pending_approval`` proposal can be decided.
5. **Binding** — the submitted ``arguments_hash`` must equal the stored hash,
   which is recomputed from the stored action to detect tampering.
6. **Revalidation** — arguments are validated again and the target machine
   must still exist, be the same machine and be active.

Execution happens in ONE transaction: the decision row (unique per proposal),
the new maintenance request (unique ``external_ref``), a conditional status
update (``WHERE status = 'pending_approval'``) and the audit events commit
together or not at all. Success is reported only after the commit, by reading
the new record back from the database.
"""

from __future__ import annotations

import hmac
import logging
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, BusinessRuleError, ConflictError, NotFoundError
from app.models.enums import (
    ApprovalDecision,
    DataSource,
    MaintenanceStatus,
    ProposalStatus,
)
from app.models.manufacturing import Machine, MaintenanceRequest
from app.models.workflow import ActionApproval, ActionProposal
from app.schemas.workflow import ApprovalCreate, PrepareMaintenanceArgs, RejectionCreate
from app.services.workflow.agent import CREATE_MAINTENANCE_REQUEST
from app.services.workflow.audit import binding_hash, record_event
from app.services.workflow.permissions import Actor, ForbiddenError, Permission, require

logger = logging.getLogger(__name__)

EXPIRY_SWEEP_LIMIT = 100


def external_ref_for(proposal_id: int) -> str:
    return f"wf-proposal-{proposal_id}"


# --------------------------------------------------------------------------- lookups


def can_view(actor: Actor, proposal: ActionProposal) -> bool:
    return (
        actor.can(Permission.VIEW_ALL_SESSIONS)
        or actor.can(Permission.DECIDE_ACTIONS)
        or proposal.proposed_by == actor.name
    )


def get_proposal(db: Session, proposal_id: int, actor: Actor) -> ActionProposal:
    proposal = db.get(ActionProposal, proposal_id)
    if proposal is None or not can_view(actor, proposal):
        # Same answer for "missing" and "not yours": ids are not disclosed.
        raise NotFoundError(f"Proposal {proposal_id} was not found")
    return proposal


# --------------------------------------------------------------------------- expiry


def _expire(db: Session, proposal: ActionProposal, now: datetime, actor: str) -> bool:
    """Mark one due proposal expired (conditional update). True if it changed."""
    changed = db.execute(
        update(ActionProposal)
        .where(
            ActionProposal.id == proposal.id,
            ActionProposal.status == ProposalStatus.PENDING_APPROVAL.value,
        )
        .values(status=ProposalStatus.EXPIRED.value, decided_at=now, updated_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    if changed:
        record_event(
            db,
            "proposal_expired",
            actor=actor,
            session_id=proposal.session_id,
            proposal_id=proposal.id,
            details={"expires_at": proposal.expires_at.isoformat()},
        )
    db.commit()
    db.refresh(proposal)
    return bool(changed)


def expire_due_proposals(db: Session, now: datetime | None = None) -> int:
    """Lazily expire pending proposals whose time is up (run before reads)."""
    now = now or datetime.now(UTC)
    due = list(
        db.scalars(
            select(ActionProposal)
            .where(
                ActionProposal.status == ProposalStatus.PENDING_APPROVAL.value,
                ActionProposal.expires_at <= now,
            )
            .limit(EXPIRY_SWEEP_LIMIT)
        )
    )
    return sum(_expire(db, proposal, now, "system") for proposal in due)


# --------------------------------------------------------------------------- shared checks


def _replayed(
    db: Session,
    proposal: ActionProposal,
    actor: Actor,
    key: str,
    decision: ApprovalDecision,
) -> bool:
    """True when this exact request was already processed (return its outcome)."""
    previous = db.scalar(select(ActionApproval).where(ActionApproval.idempotency_key == key))
    if previous is None:
        return False
    if (
        previous.proposal_id != proposal.id
        or previous.actor != actor.name
        or previous.decision != decision.value
    ):
        raise ConflictError(
            "This idempotency key was already used for a different request.",
            code="idempotency_key_reused",
        )
    record_event(
        db,
        "decision_replayed",
        actor=actor.name,
        session_id=proposal.session_id,
        proposal_id=proposal.id,
        details={"decision": decision.value},
    )
    db.commit()
    db.refresh(proposal)
    return True


def _ensure_pending(db: Session, proposal: ActionProposal, actor: Actor, now: datetime) -> None:
    if proposal.status == ProposalStatus.PENDING_APPROVAL.value and now >= proposal.expires_at:
        _expire(db, proposal, now, actor.name)
        raise ConflictError(
            "This proposal has expired. Ask the assistant again to prepare a new one.",
            code="proposal_expired",
        )
    if proposal.status != ProposalStatus.PENDING_APPROVAL.value:
        raise ConflictError(
            f"This proposal was already {proposal.status.replace('_', ' ')}; "
            "it cannot be decided again.",
            code="proposal_not_pending",
            details=[{"status": proposal.status}],
        )


def _mark_failed(
    db: Session, proposal: ActionProposal, actor: Actor, code: str, message: str, now: datetime
) -> None:
    db.execute(
        update(ActionProposal)
        .where(
            ActionProposal.id == proposal.id,
            ActionProposal.status == ProposalStatus.PENDING_APPROVAL.value,
        )
        .values(
            status=ProposalStatus.FAILED.value,
            error_code=code,
            error_message=message[:300],
            decided_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    record_event(
        db,
        "action_failed",
        actor=actor.name,
        session_id=proposal.session_id,
        proposal_id=proposal.id,
        details={"error_code": code},
    )
    db.commit()
    db.refresh(proposal)


def _revalidate(
    db: Session, proposal: ActionProposal, actor: Actor, now: datetime
) -> tuple[PrepareMaintenanceArgs, Machine]:
    """Check the stored action again against the current database state."""

    def fail(code: str, message: str) -> BusinessRuleError:
        _mark_failed(db, proposal, actor, code, message, now)
        return BusinessRuleError(message, code=code)

    if proposal.action_type != CREATE_MAINTENANCE_REQUEST:
        raise fail("unsupported_action", "This kind of action cannot be executed.")
    if not hmac.compare_digest(binding_hash(proposal), proposal.arguments_hash):
        raise fail(
            "integrity_check_failed", "The stored action does not match its approval hash."
        )
    try:
        args = PrepareMaintenanceArgs.model_validate(proposal.arguments)
    except ValidationError:
        raise fail("revalidation_failed", "The stored action is no longer valid.") from None
    machine = db.scalar(select(Machine).where(Machine.code == args.machine_code))
    target_id = (proposal.preview.get("target") or {}).get("machine_id")
    if machine is None or machine.id != target_id:
        raise fail("revalidation_failed", f"Machine {args.machine_code} no longer matches.")
    if not machine.is_active:
        raise fail("revalidation_failed", f"Machine {args.machine_code} is now inactive.")
    return args, machine


# --------------------------------------------------------------------------- decisions


def approve(
    db: Session,
    proposal_id: int,
    actor: Actor,
    body: ApprovalCreate,
    *,
    require_distinct_approver: bool,
    now: datetime | None = None,
) -> ActionProposal:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    proposal = get_proposal(db, proposal_id, actor)
    require(actor, Permission.DECIDE_ACTIONS)
    if _replayed(db, proposal, actor, body.idempotency_key, ApprovalDecision.APPROVED):
        return proposal
    if require_distinct_approver and proposal.proposed_by == actor.name:
        raise ForbiddenError(
            "You prepared this action, so another supervisor must approve it.",
            code="self_approval_forbidden",
        )
    _ensure_pending(db, proposal, actor, now)
    if not hmac.compare_digest(body.arguments_hash, proposal.arguments_hash):
        record_event(
            db,
            "approval_mismatch",
            actor=actor.name,
            session_id=proposal.session_id,
            proposal_id=proposal.id,
            details={},
        )
        db.commit()
        raise ConflictError(
            "The approval does not match this proposal's action and arguments. "
            "Reload the proposal and review it again.",
            code="approval_mismatch",
        )
    args, machine = _revalidate(db, proposal, actor, now)

    reference = external_ref_for(proposal.id)
    try:
        db.add(
            ActionApproval(
                proposal_id=proposal.id,
                decision=ApprovalDecision.APPROVED.value,
                actor=actor.name,
                actor_role=actor.role.value,
                arguments_hash=body.arguments_hash,
                idempotency_key=body.idempotency_key,
                note=body.note,
            )
        )
        request = MaintenanceRequest(
            machine_id=machine.id,
            issue_description=args.issue_description,
            priority=args.priority.value,
            status=MaintenanceStatus.OPEN.value,
            data_source=DataSource.MANUAL.value,
            external_ref=reference,
        )
        db.add(request)
        db.flush()
        result = {
            "maintenance_request_id": request.id,
            "external_ref": reference,
            "machine_code": machine.code,
            "priority": request.priority,
            "status": request.status,
        }
        claimed = db.execute(
            update(ActionProposal)
            .where(
                ActionProposal.id == proposal.id,
                ActionProposal.status == ProposalStatus.PENDING_APPROVAL.value,
            )
            .values(
                status=ProposalStatus.EXECUTED.value,
                result=result,
                result_record_type="maintenance_request",
                result_record_id=request.id,
                decided_at=now,
                executed_at=datetime.now(UTC),
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        ).rowcount
        if claimed != 1:
            raise _Raced()
        for event_type in ("action_approved", "action_executed"):
            record_event(
                db,
                event_type,
                actor=actor.name,
                session_id=proposal.session_id,
                proposal_id=proposal.id,
                details=(
                    {"note_given": body.note is not None}
                    if event_type == "action_approved"
                    else {"maintenance_request_id": request.id, "external_ref": reference}
                ),
            )
        db.commit()
    except (IntegrityError, _Raced):
        db.rollback()
        db.refresh(proposal)
        logger.info("approval lost a race or hit a constraint", extra={"proposal_id": proposal.id})
        if proposal.status != ProposalStatus.PENDING_APPROVAL.value:
            raise ConflictError(
                f"This proposal was already {proposal.status.replace('_', ' ')}.",
                code="proposal_not_pending",
                details=[{"status": proposal.status}],
            ) from None
        raise ConflictError(
            "The action could not be executed because the data changed. Nothing was created.",
            code="execution_conflict",
        ) from None

    # Confirm from the database before reporting success.
    stored = db.scalar(
        select(MaintenanceRequest).where(MaintenanceRequest.external_ref == reference)
    )
    db.refresh(proposal)
    if stored is None or proposal.result_record_id != stored.id:
        logger.error("executed action could not be confirmed", extra={"proposal_id": proposal.id})
        raise AppError(
            "The action's result could not be confirmed. Check the maintenance requests list.",
            code="execution_unconfirmed",
            status_code=500,
        )
    return proposal


class _Raced(Exception):
    """The conditional update matched no row: someone else decided first."""


def reject(
    db: Session,
    proposal_id: int,
    actor: Actor,
    body: RejectionCreate,
    *,
    now: datetime | None = None,
) -> ActionProposal:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    proposal = get_proposal(db, proposal_id, actor)
    if _replayed(db, proposal, actor, body.idempotency_key, ApprovalDecision.REJECTED):
        return proposal
    # Supervisors may reject anything; the person who prepared it may withdraw it.
    withdrawing = proposal.proposed_by == actor.name and actor.can(Permission.PROPOSE_MAINTENANCE)
    if not withdrawing:
        require(actor, Permission.DECIDE_ACTIONS)
    _ensure_pending(db, proposal, actor, now)
    try:
        db.add(
            ActionApproval(
                proposal_id=proposal.id,
                decision=ApprovalDecision.REJECTED.value,
                actor=actor.name,
                actor_role=actor.role.value,
                arguments_hash=proposal.arguments_hash,
                idempotency_key=body.idempotency_key,
                note=body.note,
            )
        )
        db.flush()
        claimed = db.execute(
            update(ActionProposal)
            .where(
                ActionProposal.id == proposal.id,
                ActionProposal.status == ProposalStatus.PENDING_APPROVAL.value,
            )
            .values(status=ProposalStatus.REJECTED.value, decided_at=now, updated_at=now)
            .execution_options(synchronize_session=False)
        ).rowcount
        if claimed != 1:
            raise _Raced()
        record_event(
            db,
            "action_rejected",
            actor=actor.name,
            session_id=proposal.session_id,
            proposal_id=proposal.id,
            details={"withdrawn_by_proposer": withdrawing, "note_given": body.note is not None},
        )
        db.commit()
    except (IntegrityError, _Raced):
        db.rollback()
        db.refresh(proposal)
        raise ConflictError(
            f"This proposal was already {proposal.status.replace('_', ' ')}.",
            code="proposal_not_pending",
            details=[{"status": proposal.status}],
        ) from None
    db.refresh(proposal)
    return proposal