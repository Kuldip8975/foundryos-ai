"""The workflow agent loop (Module 4): plan with the model, execute in code.

For each round the model receives the question and the results so far and
replies with either tool calls or a final answer. The backend then:

* refuses any tool that is not in the allowlist (``TOOLS``);
* refuses tools the person's role may not use (checked here, not by the model);
* validates arguments with the tool's Pydantic model before running anything;
* enforces the per-run tool-call limit, round limit and overall time budget;
* runs read tools inside the person's permitted scope, with a DB statement timeout;
* turns ``prepare_maintenance_request`` into a *pending* proposal — nothing is
  written to manufacturing tables until a person approves it (see approvals.py);
* records every call, refusal and outcome as steps and audit events;
* checks that every finding in the final answer cites real evidence ids.

The provider is called outside any open transaction: each step is committed
before the next model call, so no locks are held while waiting for the model.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn, Protocol

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.models.enums import ProposalStatus, WorkflowStatus, WorkflowStepStatus
from app.models.workflow import ActionProposal, WorkflowSession, WorkflowStep
from app.schemas.workflow import FinalTurn, ToolCall
from app.services.ai_provider import Prompt, ProviderError, ProviderResult, not_configured
from app.services.workflow.audit import binding_hash, record_event
from app.services.workflow.permissions import Actor, Permission, require
from app.services.workflow.prompt import PROMPT_VERSION, build_prompt, parse_turn
from app.services.workflow.tools import TOOLS, ToolError, ToolSpec, limit_statement_time

logger = logging.getLogger(__name__)

MAX_ARGUMENT_CHARS = 4000
# A model call is only started with at least this much of the budget left
# (room for one quick retry of an overloaded provider plus the call itself).
MIN_SECONDS_FOR_MODEL_CALL = 15.0
RETRY_HEADROOM_SECONDS = 12.0
CREATE_MAINTENANCE_REQUEST = "create_maintenance_request"


class AgentModel(Protocol):
    name: str
    model: str

    def generate(
        self, prompt: Prompt, *, timeout_seconds: float | None = None
    ) -> ProviderResult: ...


@dataclass(frozen=True)
class AgentLimits:
    max_tool_calls: int = 8
    max_rounds: int = 4
    timeout_seconds: float = 120.0
    proposal_ttl: timedelta = timedelta(minutes=15)

    @classmethod
    def from_settings(cls, settings: Settings) -> AgentLimits:
        return cls(
            max_tool_calls=settings.workflow_max_tool_calls,
            max_rounds=settings.workflow_max_rounds,
            timeout_seconds=settings.workflow_timeout_seconds,
            proposal_ttl=timedelta(minutes=settings.workflow_proposal_ttl_minutes),
        )


class WorkflowFailed(Exception):
    """Internal signal: stop the run with this safe error."""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _clip(value: str, limit: int = 300) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _validation_summary(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors()[:3]:
        location = ".".join(str(part) for part in error.get("loc", ())) or "arguments"
        parts.append(f"{location}: {error.get('msg')}")
    return _clip("; ".join(parts))


def _has_synthetic(result: dict[str, Any] | None) -> bool:
    sources = (result or {}).get("data_sources") or {}
    return bool(sources.get("synthetic"))


class _Run:
    """State of one workflow run."""

    def __init__(
        self,
        db: Session,
        session: WorkflowSession,
        actor: Actor,
        model: AgentModel,
        limits: AgentLimits,
        now: datetime,
        clock: Callable[[], float],
    ) -> None:
        self.db = db
        self.session = session
        self.actor = actor
        self.model = model
        self.limits = limits
        self.now = now
        self.clock = clock
        self.deadline = clock() + limits.timeout_seconds
        self.steps: list[WorkflowStep] = []
        self.evidence_ids: set[str] = set()
        self.calls_made = 0
        self.proposal: ActionProposal | None = None

    # ------------------------------------------------------------------ loop

    def execute(self) -> WorkflowSession:
        specs = [spec for spec in TOOLS.values() if self.actor.can(spec.permission)]
        for round_no in range(1, self.limits.max_rounds + 1):
            final_turn = (
                round_no == self.limits.max_rounds or self.calls_made >= self.limits.max_tool_calls
            )
            remaining = self.deadline - self.clock()
            if remaining < MIN_SECONDS_FOR_MODEL_CALL:
                raise WorkflowFailed(
                    "workflow_timeout", "The assistant ran out of time before answering.", 504
                )
            prompt = build_prompt(
                question=self.session.question,
                today=self.now.date(),
                specs=specs,
                steps=self.steps,
                calls_remaining=max(0, self.limits.max_tool_calls - self.calls_made),
                final_turn=final_turn,
                proposal=self._proposal_summary(),
                machine_scope=self.actor.machine_codes,
            )
            result = self.model.generate(
                prompt, timeout_seconds=max(5.0, remaining - RETRY_HEADROOM_SECONDS)
            )
            self.session.model = result.model
            turn = parse_turn(result.text, self.evidence_ids)
            if isinstance(turn, FinalTurn):
                return self._complete(turn)
            if final_turn:
                raise WorkflowFailed(
                    "agent_step_limit",
                    "The assistant did not finish within its step limit. "
                    "Try a narrower question.",
                    502,
                )
            for call in turn.calls:
                self._run_call(call, round_no)
        raise WorkflowFailed(  # pragma: no cover - the last round is always a final turn
            "agent_step_limit", "The assistant did not finish within its step limit.", 502
        )

    # ------------------------------------------------------------------ tool calls

    def _run_call(self, call: ToolCall, round_no: int) -> None:
        started = time.perf_counter()
        step = WorkflowStep(
            session_id=self.session.id,
            sequence=len(self.steps) + 1,
            round=round_no,
            tool=call.tool,
            arguments=call.arguments,
            status=WorkflowStepStatus.REJECTED.value,
            duration_ms=0,
        )
        spec = TOOLS.get(call.tool)
        refusal = self._refusal(call, spec)
        self.calls_made += 1
        if refusal is not None:
            step.error_code, step.error_message = refusal
            if refusal[0] == "arguments_too_large":
                step.arguments = {"note": "arguments omitted: too large"}
        else:
            assert spec is not None
            try:
                args = spec.args_model.model_validate(call.arguments)
            except ValidationError as exc:
                step.error_code, step.error_message = "invalid_arguments", _validation_summary(exc)
            else:
                step.arguments = args.model_dump(mode="json", exclude_none=True)
                scope_refusal = self._scope_refusal(spec, args)
                if scope_refusal is not None:
                    step.error_code, step.error_message = scope_refusal
                else:
                    self._invoke(spec, args, step)
        step.duration_ms = round((time.perf_counter() - started) * 1000)
        self.db.add(step)
        self.steps.append(step)
        self.session.tool_call_count = self.calls_made
        if _has_synthetic(step.result):
            self.session.includes_synthetic_data = True
        record_event(
            self.db,
            "tool_call" if step.status == WorkflowStepStatus.OK.value else "tool_call_refused",
            actor=self.actor.name,
            session_id=self.session.id,
            proposal_id=(
                self.proposal.id
                if self.proposal is not None and spec is not None and spec.prepares_change
                else None
            ),
            details={
                "sequence": step.sequence,
                "tool": _clip(call.tool, 64),
                "status": step.status,
                "error_code": step.error_code,
            },
        )
        self.db.commit()

    def _refusal(self, call: ToolCall, spec: ToolSpec | None) -> tuple[str, str] | None:
        if self.calls_made >= self.limits.max_tool_calls:
            return "tool_call_limit", "The tool-call limit for this question was reached."
        if spec is None:
            return "unknown_tool", f"'{_clip(call.tool, 64)}' is not an available tool."
        if not self.actor.can(spec.permission):
            return "forbidden", f"Your role ({self.actor.role.value}) cannot use {spec.name}."
        if len(json.dumps(call.arguments, default=str)) > MAX_ARGUMENT_CHARS:
            return "arguments_too_large", "The tool arguments were too large."
        if spec.prepares_change and self.proposal is not None:
            return "proposal_limit", "Only one action can be prepared per question."
        if self.clock() > self.deadline:
            return "workflow_timeout", "The time budget for this question was used up."
        return None

    def _scope_refusal(self, spec: ToolSpec, args: Any) -> tuple[str, str] | None:
        """Machine-scoped people (operators) only reach their assigned machines."""
        scope = self.actor.machine_codes
        if scope is None:
            return None
        allowed = ", ".join(sorted(scope)) or "none"
        code = getattr(args, "machine_code", None)
        if code is None:
            if spec.lists_machines:
                return None  # the handler limits the list to the assigned machines
            return (
                "machine_required",
                f"Name one of your assigned machines in machine_code ({allowed}).",
            )
        if code not in scope:
            return (
                "machine_not_assigned",
                f"Machine {_clip(code, 50)} is not assigned to you. Assigned: {allowed}.",
            )
        return None

    def _invoke(self, spec: ToolSpec, args: Any, step: WorkflowStep) -> None:
        try:
            limit_statement_time(self.db)
            if spec.lists_machines and self.actor.machine_codes is not None:
                result = spec.handler(
                    self.db, args, self.now, only_codes=self.actor.machine_codes
                )
            else:
                result = spec.handler(self.db, args, self.now)
        except ToolError as exc:
            step.status = WorkflowStepStatus.ERROR.value
            step.error_code, step.error_message = exc.code, _clip(exc.message)
            return
        except SQLAlchemyError as exc:
            # e.g. the statement timeout fired. Earlier steps are already committed.
            self.db.rollback()
            logger.warning("workflow tool query failed", extra={"error_type": type(exc).__name__})
            step.status = WorkflowStepStatus.ERROR.value
            step.error_code = "query_failed"
            step.error_message = "The data query failed or took too long."
            return
        step.status = WorkflowStepStatus.OK.value
        step.result = result
        step.evidence_id = f"E{len(self.evidence_ids) + 1}"
        self.evidence_ids.add(step.evidence_id)
        if spec.prepares_change:
            self._create_proposal(args, result)

    def _create_proposal(self, args: Any, preview: dict[str, Any]) -> None:
        proposal = ActionProposal(
            session_id=self.session.id,
            action_type=CREATE_MAINTENANCE_REQUEST,
            arguments=args.model_dump(mode="json"),
            preview=preview,
            arguments_hash="0" * 64,  # replaced below, once the id is known
            status=ProposalStatus.PENDING_APPROVAL.value,
            proposed_by=self.actor.name,
            expires_at=self.now + self.limits.proposal_ttl,
        )
        self.db.add(proposal)
        self.db.flush()
        proposal.arguments_hash = binding_hash(proposal)
        self.proposal = proposal
        record_event(
            self.db,
            "action_proposed",
            actor=self.actor.name,
            session_id=self.session.id,
            proposal_id=proposal.id,
            details={
                "action_type": proposal.action_type,
                "machine_code": preview.get("machine_code"),
                "priority": preview.get("priority"),
                "expires_at": proposal.expires_at.isoformat(),
            },
        )

    def _proposal_summary(self) -> dict[str, Any] | None:
        if self.proposal is None:
            return None
        return {
            "status": self.proposal.status,
            "action": self.proposal.action_type,
            "note": "Prepared only. A person must approve it; it has NOT been created.",
        }

    # ------------------------------------------------------------------ outcome

    def _complete(self, turn: FinalTurn) -> WorkflowSession:
        self.session.answer = turn.model_dump(mode="json", exclude={"type"})
        self.session.status = WorkflowStatus.COMPLETED.value
        self.session.completed_at = datetime.now(UTC)
        record_event(
            self.db,
            "workflow_completed",
            actor=self.actor.name,
            session_id=self.session.id,
            details={
                "tool_calls": self.calls_made,
                "findings": len(turn.findings),
                "proposal_id": self.proposal.id if self.proposal else None,
            },
        )
        self.db.commit()
        return self.session


def run_workflow(
    db: Session,
    *,
    question: str,
    actor: Actor,
    model: AgentModel | None,
    limits: AgentLimits,
    now: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> WorkflowSession:
    """Answer one question. Returns the completed session or raises a safe AppError
    whose details carry the stored ``session_id``."""
    require(actor, Permission.RUN_WORKFLOW)
    if model is None:
        error = not_configured()
        raise AppError(
            "The workflow assistant is not configured on the server.",
            code="ai_not_configured",
            status_code=error.http_status,
        )
    now = (now or datetime.now(UTC)).astimezone(UTC)

    session = WorkflowSession(
        actor=actor.name,
        actor_role=actor.role.value,
        question=question,
        status=WorkflowStatus.RUNNING.value,
        provider=model.name,
        model=model.model,
        prompt_version=PROMPT_VERSION,
        tool_call_count=0,
        includes_synthetic_data=False,
    )
    db.add(session)
    db.flush()
    record_event(
        db,
        "workflow_started",
        actor=actor.name,
        session_id=session.id,
        details={"role": actor.role.value, "question_length": len(question)},
    )
    db.commit()

    run = _Run(db, session, actor, model, limits, now, clock)
    try:
        return run.execute()
    except ProviderError as error:
        _fail(db, session, actor, error.code, error.message, error.http_status)
    except WorkflowFailed as error:
        _fail(db, session, actor, error.code, error.message, error.http_status)
    except Exception:
        logger.exception("unexpected error during a workflow run")
        db.rollback()
        _mark_failed(db, session, actor, "workflow_internal_error", "The workflow failed.")
        raise


def _mark_failed(
    db: Session, session: WorkflowSession, actor: Actor, code: str, message: str
) -> None:
    session.status = WorkflowStatus.FAILED.value
    session.error_code = code
    session.error_message = _clip(message)
    session.completed_at = datetime.now(UTC)
    record_event(
        db, "workflow_failed", actor=actor.name, session_id=session.id, details={"error_code": code}
    )
    db.commit()


def _fail(
    db: Session, session: WorkflowSession, actor: Actor, code: str, message: str, status: int
) -> NoReturn:
    _mark_failed(db, session, actor, code, message)
    raise AppError(message, code=code, status_code=status, details=[{"session_id": session.id}])