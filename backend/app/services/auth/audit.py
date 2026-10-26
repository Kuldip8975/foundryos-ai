"""Access audit events (Module 5). The caller commits.

Details hold ids, codes, role names and counts only — never passwords,
tokens, token hashes or text typed into a failed sign-in.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.auth import AuthAuditEvent, User


def record_auth_event(
    db: Session,
    event_type: str,
    *,
    actor: User | None = None,
    actor_username: str | None = None,
    target: User | None = None,
    success: bool = True,
    details: dict[str, Any] | None = None,
) -> AuthAuditEvent:
    event = AuthAuditEvent(
        event_type=event_type,
        actor_user_id=actor.id if actor is not None else None,
        actor_username=actor.username if actor is not None else actor_username,
        target_user_id=target.id if target is not None else None,
        target_username=target.username if target is not None else None,
        success=success,
        details=details or {},
    )
    db.add(event)
    return event