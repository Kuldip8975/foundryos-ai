"""Workflow assistant API (Module 4) — thin HTTP layer over app.services.workflow.

Every endpoint requires ``Authorization: Bearer <token>``. The token is either
a signed-in user's session (Module 5; the user's role is mapped to a workflow
role by app.core.permissions.WORKFLOW_ROLE and operators are limited to their
assigned machines) or, for backward compatibility, a legacy access token from
WORKFLOW_ACCESS_TOKENS (app.core.security). The role decides what the person
may do; the language model never does.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi import status as http_status
from sqlalchemy import select

from app.api.auth import bearer_token, principal_from_token
from app.api.deps import DbSession, EntityPathId, PageParams, get_app_settings
from app.api.routes.responses import ERROR_RESPONSES
from app.core.config import Settings
from app.core.errors import AuthenticationError, ForbiddenError
from app.core.permissions import WORKFLOW_ROLE
from app.core.permissions import Permission as UserPermission
from app.core.security import MIN_TOKEN_LENGTH, authenticate
from app.models.enums import ProposalStatus, WorkflowStatus
from app.models.manufacturing import Machine
from app.schemas.common import Page
from app.schemas.errors import ErrorResponse
from app.schemas.workflow import (
    ActorRead,
    ApprovalCreate,
    ProposalRead,
    RejectionCreate,
    WorkflowRunCreate,
    WorkflowSessionRead,
    WorkflowSessionSummary,
)
from app.services.ai_provider import GeminiProvider
from app.services.workflow import approvals, sessions
from app.services.workflow.agent import AgentLimits, AgentModel, run_workflow
from app.services.workflow.permissions import Actor

WORKFLOW_RESPONSES: dict[int | str, dict[str, Any]] = {
    **ERROR_RESPONSES,
    401: {"model": ErrorResponse, "description": "Missing or invalid access token"},
    403: {"model": ErrorResponse, "description": "The role does not allow this"},
    429: {"model": ErrorResponse, "description": "AI provider rate limit"},
    502: {"model": ErrorResponse, "description": "AI provider error or invalid AI output"},
    503: {"model": ErrorResponse, "description": "Workflow assistant not configured"},
    504: {"model": ErrorResponse, "description": "AI provider or workflow timeout"},
}

router = APIRouter(prefix="/workflows", tags=["workflow assistant"], responses=WORKFLOW_RESPONSES)

def get_actor(
    request: Request,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> Actor:
    token = bearer_token(request)
    if token is None:
        raise AuthenticationError()
    entries = settings.workflow_access_entries
    if entries and len(token) >= MIN_TOKEN_LENGTH:
        entry = authenticate(entries, token)
        if entry is not None:  # legacy Module 4 access token
            return Actor(name=entry.name, role=entry.role)
    principal = principal_from_token(db, settings, token)
    if principal.must_change_password:
        raise ForbiddenError(
            "Change your temporary password before continuing.",
            code="password_change_required",
        )
    principal.require(UserPermission.ASSISTANT_USE)
    role = WORKFLOW_ROLE[principal.role]
    if role is None:  # pragma: no cover - roles without ASSISTANT_USE map to None
        raise ForbiddenError("Your role does not allow this.")
    codes = None
    if principal.machine_ids is not None:
        codes = frozenset(
            db.scalars(select(Machine.code).where(Machine.id.in_(sorted(principal.machine_ids))))
        )
    return Actor(name=principal.username, role=role, machine_codes=codes)


def get_agent_model(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> AgentModel | None:
    """The configured model, or None when the assistant is disabled or has no key."""
    if not settings.workflow_ai_configured or settings.gemini_api_key is None:
        return None
    return GeminiProvider(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_model,
        timeout_seconds=settings.ai_request_timeout_seconds,
        thinking_level=settings.gemini_thinking_level or None,
    )


CurrentActor = Annotated[Actor, Depends(get_actor)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]


@router.get("/me", response_model=ActorRead, summary="Who the access token belongs to")
def read_me(actor: CurrentActor) -> Any:
    return ActorRead(
        name=actor.name,
        role=actor.role,
        permissions=sorted(permission.value for permission in actor.permissions),
    )


@router.post(
    "",
    response_model=WorkflowSessionRead,
    status_code=http_status.HTTP_201_CREATED,
    summary="Ask the assistant a question (read-only tools; changes are only proposed)",
)
def create_workflow(
    payload: WorkflowRunCreate,
    db: DbSession,
    actor: CurrentActor,
    settings: AppSettings,
    model: Annotated[AgentModel | None, Depends(get_agent_model)],
) -> Any:
    session = run_workflow(
        db,
        question=payload.question,
        actor=actor,
        model=model,
        limits=AgentLimits.from_settings(settings),
    )
    # Serialise here, while the database session is certainly open.
    return WorkflowSessionRead.model_validate(session)


@router.get("", response_model=Page[WorkflowSessionSummary], summary="Workflow history")
def list_workflows(
    db: DbSession,
    actor: CurrentActor,
    page: PageParams,
    status_: Annotated[WorkflowStatus | None, Query(alias="status")] = None,
    proposal_status: Annotated[ProposalStatus | None, Query()] = None,
) -> Any:
    items, total = sessions.list_sessions(
        db,
        actor,
        sessions.SessionFilters(status=status_, proposal_status=proposal_status),
        limit=page.limit,
        offset=page.offset,
    )
    return Page[WorkflowSessionSummary](
        items=[WorkflowSessionSummary.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/proposals/{proposal_id}/approve",
    response_model=ProposalRead,
    summary="Approve and execute exactly the proposed action",
)
def approve_proposal(
    proposal_id: EntityPathId,
    payload: ApprovalCreate,
    db: DbSession,
    actor: CurrentActor,
    settings: AppSettings,
) -> Any:
    proposal = approvals.approve(
        db,
        proposal_id,
        actor,
        payload,
        require_distinct_approver=settings.workflow_require_distinct_approver,
    )
    return ProposalRead.model_validate(proposal)


@router.post(
    "/proposals/{proposal_id}/reject",
    response_model=ProposalRead,
    summary="Reject (or, for its author, withdraw) a proposed action",
)
def reject_proposal(
    proposal_id: EntityPathId, payload: RejectionCreate, db: DbSession, actor: CurrentActor
) -> Any:
    return ProposalRead.model_validate(approvals.reject(db, proposal_id, actor, payload))


@router.get(
    "/{session_id}", response_model=WorkflowSessionRead, summary="One session with its audit trail"
)
def read_workflow(session_id: EntityPathId, db: DbSession, actor: CurrentActor) -> Any:
    return WorkflowSessionRead.model_validate(sessions.get_session(db, session_id, actor))