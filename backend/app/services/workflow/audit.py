"""Audit events and approval binding for the workflow assistant (Module 4)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.workflow import ActionProposal, WorkflowAuditEvent


def record_event(
    db: Session,
    event_type: str,
    *,
    actor: str,
    session_id: int | None = None,
    proposal_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> WorkflowAuditEvent:
    """Add an audit event to the current unit of work (the caller commits).

    Details hold ids, codes and counts — never tokens, prompts or model text.
    """
    event = WorkflowAuditEvent(
        event_type=event_type,
        actor=actor,
        session_id=session_id,
        proposal_id=proposal_id,
        details=details or {},
    )
    db.add(event)
    return event


def binding_hash(proposal: ActionProposal) -> str:
    """SHA-256 over everything an approval authorises.

    It covers the proposal and session ids, the action, its exact arguments,
    the resolved target record and the expiry time. An approval must send this
    value back, so it can only approve the action that was displayed: a
    different proposal, edited arguments or a changed target all produce a
    different hash.
    """
    canonical = json.dumps(
        {
            "proposal_id": proposal.id,
            "session_id": proposal.session_id,
            "action_type": proposal.action_type,
            "arguments": proposal.arguments,
            "target": (proposal.preview or {}).get("target"),
            "expires_at": proposal.expires_at.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()