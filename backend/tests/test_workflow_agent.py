"""Workflow agent limits and access tokens (Module 4), tested below the HTTP layer.

The model is a scripted fake and the clock is controlled by the test, so
limits and timeouts are checked deterministically and without network calls.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.cli import workflow_token
from app.core.errors import AppError
from app.core.security import authenticate, hash_token, parse_access_entries
from app.models.enums import WorkflowRole
from app.models.manufacturing import Machine
from app.models.workflow import WorkflowSession
from app.services.ai_provider import Prompt, ProviderResult
from app.services.workflow.agent import AgentLimits, run_workflow
from app.services.workflow.permissions import ROLE_PERMISSIONS, Actor, Permission
from app.services.workflow.tools import TOOLS

SUPERVISOR = Actor(name="alice", role=WorkflowRole.SUPERVISOR)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class ScriptedModel:
    name = "fake"
    model = "fake-agent-1"

    def __init__(self, replies: list[dict[str, Any]], clock: Clock | None = None, step: float = 0):
        self.replies = list(replies)
        self.prompts: list[Prompt] = []
        self.timeouts: list[float | None] = []
        self.clock = clock
        self.step = step

    def generate(self, prompt: Prompt, *, timeout_seconds: float | None = None) -> ProviderResult:
        self.prompts.append(prompt)
        self.timeouts.append(timeout_seconds)
        if self.clock is not None:
            self.clock.now += self.step  # each model call "takes" this long
        return ProviderResult(
            text=json.dumps(self.replies.pop(0)), provider=self.name, model=self.model
        )


def status_calls(n: int) -> dict[str, Any]:
    return {
        "type": "tool_calls",
        "calls": [{"tool": "get_machine_status", "arguments": {}} for _ in range(n)],
    }


def final(*evidence: str) -> dict[str, Any]:
    findings = [{"statement": "Fact.", "evidence": list(evidence)}] if evidence else []
    return {"type": "final", "answer": "Answer.", "findings": findings, "limitations": []}


@pytest.fixture
def mill(db_session: Session) -> Machine:
    machine = Machine(code="MILL", name="Mill")
    db_session.add(machine)
    db_session.commit()
    return machine


def test_tool_call_limit_is_enforced_by_the_backend(db_session: Session, mill: Machine) -> None:
    model = ScriptedModel([status_calls(4), final("E1", "E2")])
    session = run_workflow(
        db_session,
        question="Status?",
        actor=SUPERVISOR,
        model=model,
        limits=AgentLimits(max_tool_calls=2, max_rounds=3),
    )
    outcomes = [(step.status, step.error_code) for step in session.steps]
    assert outcomes == [
        ("ok", None),
        ("ok", None),
        ("rejected", "tool_call_limit"),
        ("rejected", "tool_call_limit"),
    ]
    second = json.loads(model.prompts[1].user)
    assert (second["TOOL_CALLS_REMAINING"], second["FINAL_TURN"]) == (0, True)
    assert session.status == "completed"


def test_round_limit_stops_a_model_that_never_answers(db_session: Session, mill: Machine) -> None:
    model = ScriptedModel([status_calls(1), status_calls(1)])
    with pytest.raises(AppError) as caught:
        run_workflow(
            db_session,
            question="Status?",
            actor=SUPERVISOR,
            model=model,
            limits=AgentLimits(max_rounds=2),
        )
    assert caught.value.code == "agent_step_limit"
    session_id = caught.value.details[0]["session_id"]
    db_session.expire_all()
    stored = db_session.get(WorkflowSession, session_id)
    assert (stored.status, stored.error_code) == ("failed", "agent_step_limit")
    assert len(model.prompts) == 2


def test_overall_time_budget_is_enforced(db_session: Session, mill: Machine) -> None:
    clock = Clock()
    model = ScriptedModel([status_calls(1), final("E1")], clock=clock, step=10)
    with pytest.raises(AppError) as caught:
        run_workflow(
            db_session,
            question="Status?",
            actor=SUPERVISOR,
            model=model,
            limits=AgentLimits(timeout_seconds=20),
            clock=clock,
        )
    assert (caught.value.code, caught.value.status_code) == ("workflow_timeout", 504)
    # The first call was given only what was left of the budget, minus retry headroom.
    assert model.timeouts == [8.0]


def test_viewers_cannot_run_change_tools_even_if_named(db_session: Session, mill: Machine) -> None:
    viewer = Actor(name="vic", role=WorkflowRole.VIEWER)
    model = ScriptedModel([
        {
            "type": "tool_calls",
            "calls": [{
                "tool": "prepare_maintenance_request",
                "arguments": {
                    "machine_code": "MILL",
                    "issue_description": "Noise from the gearbox",
                    "priority": "low",
                },
            }],
        },
        final(),
    ])
    session = run_workflow(
        db_session, question="Raise a request", actor=viewer, model=model, limits=AgentLimits()
    )
    assert [(s.status, s.error_code) for s in session.steps] == [("rejected", "forbidden")]
    assert session.proposal is None


# --------------------------------------------------------------------------- allowlist + roles


def test_allowlist_is_exactly_the_documented_tools() -> None:
    assert set(TOOLS) == {
        "get_machine_status",
        "query_downtime",
        "get_production_quality_metrics",
        "list_maintenance_requests",
        "prepare_maintenance_request",
    }
    changing = {name for name, spec in TOOLS.items() if spec.prepares_change}
    assert changing == {"prepare_maintenance_request"}
    assert TOOLS["prepare_maintenance_request"].permission == Permission.PROPOSE_MAINTENANCE


def test_role_permissions() -> None:
    assert Permission.DECIDE_ACTIONS not in ROLE_PERMISSIONS[WorkflowRole.OPERATOR]
    assert Permission.PROPOSE_MAINTENANCE not in ROLE_PERMISSIONS[WorkflowRole.VIEWER]
    assert ROLE_PERMISSIONS[WorkflowRole.SUPERVISOR] == frozenset(Permission)


# --------------------------------------------------------------------------- access tokens

SAMPLE = "a-sufficiently-long-random-token-value"


def test_tokens_are_matched_by_hash() -> None:
    entries = parse_access_entries(
        f"alice:supervisor:{hash_token(SAMPLE)}, bob:viewer:{hash_token(SAMPLE + 'x')}"
    )
    assert authenticate(entries, SAMPLE).name == "alice"
    assert authenticate(entries, SAMPLE + "x").role == WorkflowRole.VIEWER
    assert authenticate(entries, "a-wrong-but-long-enough-token-value") is None
    assert authenticate(entries, "short") is None
    assert hash_token(SAMPLE) not in repr(entries)


@pytest.mark.parametrize(
    "raw",
    [
        "alice:supervisor",
        "alice:root:" + "a" * 64,
        "alice:viewer:" + "z" * 64,
        "al ice:viewer:" + "a" * 64,
        f"alice:viewer:{'a' * 64},bob:viewer:{'a' * 64}",
    ],
    ids=["missing-hash", "unknown-role", "not-hex", "bad-name", "duplicate-hash"],
)
def test_malformed_entries_are_refused(raw: str) -> None:
    with pytest.raises(ValueError) as caught:
        parse_access_entries(raw)
    assert "a" * 64 not in str(caught.value)  # errors never echo the hash


def test_token_cli_prints_a_matching_entry(capsys: pytest.CaptureFixture[str]) -> None:
    assert workflow_token.main(["carol", "operator"]) == 0
    lines = [line.strip() for line in capsys.readouterr().out.splitlines() if line.strip()]
    token, entry = lines[1], lines[-1]
    name, role, digest = entry.split(":")
    assert (name, role, digest) == ("carol", "operator", hash_token(token))
    assert authenticate(parse_access_entries(entry), token).name == "carol"