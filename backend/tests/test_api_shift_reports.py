"""Shift analysis and AI shift report API (Module 3).

The AI provider is always replaced by an in-process fake: no network calls and
no real API quota are used.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.shift_reports import get_report_provider
from app.models.reports import ShiftReport
from app.services import ai_provider
from app.services.ai_provider import GeminiProvider, ProviderResult
from app.services.shift_reports import PROMPT_VERSION
from tests.conftest import make_settings
from tests.helpers import (
    API,
    defect_category,
    error_code,
    machine,
    post,
    product,
    production_record,
)

ANALYSIS = f"{API}/shift-analysis"
REPORTS = f"{API}/shift-reports"
SHIFT = {"production_date": "2026-01-10", "shift": "A"}


class FakeProvider:
    name = "fake"
    model = "fake-model-1"

    def __init__(self, outcome: str | Exception) -> None:
        self.outcome = outcome
        self.prompts: list[ai_provider.Prompt] = []

    def generate(self, prompt: ai_provider.Prompt) -> ProviderResult:
        self.prompts.append(prompt)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return ProviderResult(text=self.outcome, provider=self.name, model=self.model)


def valid_report(evidence: str = "production.actual_quantity") -> dict:
    return {
        "executive_summary": "Output was below target.",
        "production_performance": [
            {"statement": "Actual output was 95 units.", "kind": "measured_fact",
             "evidence": [evidence, "production.target_achievement"]},
        ],
        "quality_observations": [
            {"statement": "Defects may relate to tooling.", "kind": "possible_explanation",
             "evidence": ["quality.defect_rate"]},
        ],
        "downtime_maintenance_observations": [],
        "recommendations": [
            {"priority": "low", "action": "Review the shift log.", "rationale": "Context.",
             "evidence": ["production.pending_quantity"]},
            {"priority": "high", "action": "Check rejected units.", "rationale": "Above usual.",
             "evidence": ["production.rejected_quantity"]},
        ],
        "data_limitations": ["No shift window was given."],
    }


@pytest.fixture
def use_provider(app: FastAPI):
    def install(outcome: str | Exception) -> FakeProvider:
        fake = FakeProvider(outcome)
        app.dependency_overrides[get_report_provider] = lambda: fake
        return fake

    return install


@pytest.fixture
def shift_data(api: TestClient) -> dict:
    mill = machine(api, "MILL")
    part = product(api)
    dim = defect_category(api, "DIM")
    current = production_record(
        api, part["id"], machine_id=mill["id"], production_date="2026-01-10", shift="A",
        target_quantity=100, actual_quantity=95, accepted_quantity=88, rejected_quantity=5,
        notes="CONFIDENTIAL-NOTE",
    )
    production_record(
        api, part["id"], machine_id=mill["id"], production_date="2026-01-09", shift="A",
        target_quantity=100, actual_quantity=80, accepted_quantity=75, rejected_quantity=5,
    )
    post(api, "/quality-inspections", {
        "production_record_id": current["id"], "inspected_at": "2026-01-10T10:00:00Z",
        "inspected_quantity": 50, "defect_quantity": 2, "defect_category_id": dim["id"],
        "notes": "CONFIDENTIAL-INSPECTION",
    })
    post(api, "/maintenance-requests", {
        "machine_id": mill["id"], "issue_description": "CONFIDENTIAL-ISSUE", "priority": "high",
    })
    return {"mill": mill, "record": current}


# --------------------------------------------------------------------------- analysis


def test_shift_analysis_returns_deterministic_metrics(api: TestClient, shift_data: dict) -> None:
    response = api.get(ANALYSIS, params=SHIFT)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["production"]["actual_quantity"] == 95
    assert body["production"]["rejection_rate"] == pytest.approx(5 / 95)
    assert body["quality"]["defect_rate"] == pytest.approx(2 / 50)
    assert body["previous"]["production_date"] == "2026-01-09"
    assert body["comparison"]["actual_quantity_change"] == 15
    assert body["maintenance"]["open_now"] == 1


def test_shift_analysis_with_window(api: TestClient, shift_data: dict) -> None:
    post(api, "/downtime-events", {
        "machine_id": shift_data["mill"]["id"], "started_at": "2026-01-10T07:00:00Z",
        "ended_at": "2026-01-10T07:45:00Z", "reason": "Tool change",
    })
    params = {**SHIFT, "window_start": "2026-01-10T06:00:00Z", "window_end": "2026-01-10T14:00:00Z"}
    body = api.get(ANALYSIS, params=params).json()
    assert body["downtime"]["downtime_seconds"] == 45 * 60
    assert body["window_start"] == "2026-01-10T06:00:00Z"


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"window_start": "2026-01-10T06:00:00Z"}, "validation_error"),  # one-sided window
        ({"window_start": "2026-01-10T14:00:00Z", "window_end": "2026-01-10T06:00:00Z"},
         "validation_error"),
        ({"window_start": "2026-01-10T06:00:00Z", "window_end": "2026-01-11T07:00:00Z"},
         "validation_error"),  # longer than 24 h
        ({"window_start": "2026-01-10T06:00:00", "window_end": "2026-01-10T14:00:00"},
         "validation_error"),  # naive timestamps
        ({"shift": "night shift"}, "validation_error"),
        ({"window_start": "2026-01-20T06:00:00Z", "window_end": "2026-01-20T14:00:00Z"},
         "window_date_mismatch"),
    ],
)
def test_shift_analysis_validation(api: TestClient, params: dict, code: str) -> None:
    response = api.get(ANALYSIS, params={**SHIFT, **params})
    assert response.status_code == 422
    assert error_code(response) == code


def test_future_shift_is_rejected(api: TestClient) -> None:
    future = (datetime.now(UTC).date() + timedelta(days=3)).isoformat()
    response = api.get(ANALYSIS, params={"production_date": future, "shift": "A"})
    assert response.status_code == 422
    assert error_code(response) == "future_date"


# --------------------------------------------------------------------------- generation


def test_missing_configuration_returns_503_and_stores_nothing(
    api: TestClient, shift_data: dict
) -> None:
    response = api.post(REPORTS, json=SHIFT)  # default test settings: AI disabled
    assert response.status_code == 503
    assert error_code(response) == "ai_not_configured"
    assert api.get(REPORTS).json()["total"] == 0


def test_generate_and_retrieve_report(api: TestClient, shift_data: dict, use_provider) -> None:
    fake = use_provider(json.dumps(valid_report()))
    response = api.post(REPORTS, json=SHIFT)
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["status"] == "completed"
    assert report["provider"] == "fake" and report["model"] == "fake-model-1"
    assert report["prompt_version"] == PROMPT_VERSION
    assert len(report["input_fingerprint"]) == 64
    assert report["includes_synthetic_data"] is False
    # recommendations come back ordered by priority
    assert [r["priority"] for r in report["content"]["recommendations"]] == ["high", "low"]
    # the stored snapshot is exactly the deterministic analysis
    assert report["metrics"] == api.get(ANALYSIS, params=SHIFT).json()

    fetched = api.get(f"{REPORTS}/{report['id']}").json()
    assert fetched == report
    assert len(fake.prompts) == 1


def test_prompt_contains_only_aggregates(api: TestClient, shift_data: dict, use_provider) -> None:
    fake = use_provider(json.dumps(valid_report()))
    api.post(REPORTS, json=SHIFT)
    prompt = fake.prompts[0]
    for secret in ("CONFIDENTIAL-NOTE", "CONFIDENTIAL-INSPECTION", "CONFIDENTIAL-ISSUE"):
        assert secret not in prompt.user and secret not in prompt.system
    facts = json.loads(prompt.user)["FACTS"]
    assert facts["production.actual_quantity"] == 95


def test_identical_data_reuses_the_report(api: TestClient, shift_data: dict, use_provider) -> None:
    fake = use_provider(json.dumps(valid_report()))
    first = api.post(REPORTS, json=SHIFT)
    again = api.post(REPORTS, json=SHIFT)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]
    assert len(fake.prompts) == 1

    forced = api.post(REPORTS, json={**SHIFT, "regenerate": True})
    assert forced.status_code == 201
    assert forced.json()["id"] != first.json()["id"]
    assert len(fake.prompts) == 2


def test_changed_data_generates_a_new_report(
    api: TestClient, shift_data: dict, use_provider
) -> None:
    use_provider(json.dumps(valid_report()))
    first = api.post(REPORTS, json=SHIFT).json()
    record_url = f"{API}/production-records/{shift_data['record']['id']}"
    api.patch(record_url, json={"actual_quantity": 96})
    second = api.post(REPORTS, json=SHIFT)
    assert second.status_code == 201
    assert second.json()["input_fingerprint"] != first["input_fingerprint"]


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ai_provider.timeout_error(), 504, "ai_timeout"),
        (ai_provider.rate_limited(), 429, "ai_rate_limited"),
        (ai_provider.auth_failed(), 502, "ai_auth_failed"),
        (ai_provider.unavailable(), 502, "ai_unavailable"),
        (ai_provider.bad_response("No content was returned."), 502, "ai_bad_response"),
    ],
)
def test_provider_failures_are_stored_and_reported_safely(
    api: TestClient, shift_data: dict, use_provider, error, status: int, code: str
) -> None:
    use_provider(error)
    response = api.post(REPORTS, json=SHIFT)
    assert response.status_code == status
    assert error_code(response) == code
    report_id = response.json()["error"]["details"][0]["report_id"]

    stored = api.get(f"{REPORTS}/{report_id}").json()
    assert stored["status"] == "failed"
    assert stored["error_code"] == code
    assert stored["content"] is None
    assert stored["metrics"]["production"]["actual_quantity"] == 95  # still traceable


@pytest.mark.parametrize(
    "output",
    [
        "this is not json",
        json.dumps({**valid_report(), "invented_section": "x"}),
        json.dumps(valid_report(evidence="production.made_up_metric")),
        json.dumps({k: v for k, v in valid_report().items() if k != "executive_summary"}),
    ],
)
def test_invalid_ai_output_is_rejected(
    api: TestClient, shift_data: dict, use_provider, output: str
) -> None:
    use_provider(output)
    response = api.post(REPORTS, json=SHIFT)
    assert response.status_code == 502
    assert error_code(response) == "ai_invalid_output"
    assert output not in response.text  # raw model output is never echoed
    reports = api.get(REPORTS).json()["items"]
    assert [r["status"] for r in reports] == ["failed"]


def test_unexpected_provider_error_marks_report_failed(
    api: TestClient, shift_data: dict, use_provider
) -> None:
    use_provider(RuntimeError("boom with secret details"))
    response = api.post(REPORTS, json=SHIFT)
    assert response.status_code == 500
    assert "boom" not in response.text
    [report] = api.get(REPORTS).json()["items"]
    assert (report["status"], report["error_code"]) == ("failed", "ai_internal_error")


# --------------------------------------------------------------------------- duplicates


def _pending(db: Session, created_at: datetime) -> ShiftReport:
    row = ShiftReport(
        request_key="2026-01-10|A|-|-|all", production_date=datetime(2026, 1, 10).date(),
        shift="A", status="pending", prompt_version=PROMPT_VERSION, input_fingerprint="0" * 64,
        metrics={}, created_at=created_at, updated_at=created_at,
    )
    db.add(row)
    db.commit()
    return row


def test_concurrent_duplicate_request_is_rejected(
    api: TestClient, shift_data: dict, use_provider, db_session: Session
) -> None:
    fake = use_provider(json.dumps(valid_report()))
    _pending(db_session, datetime.now(UTC))
    response = api.post(REPORTS, json=SHIFT)
    assert response.status_code == 409
    assert error_code(response) == "report_in_progress"
    assert fake.prompts == []


def test_abandoned_pending_report_does_not_block(
    api: TestClient, shift_data: dict, use_provider, db_session: Session
) -> None:
    use_provider(json.dumps(valid_report()))
    stale = _pending(db_session, datetime.now(UTC) - timedelta(minutes=30))
    response = api.post(REPORTS, json=SHIFT)
    assert response.status_code == 201
    db_session.expire_all()
    old = db_session.scalars(select(ShiftReport).where(ShiftReport.id == stale.id)).one()
    assert (old.status, old.error_code) == ("failed", "ai_abandoned")


# --------------------------------------------------------------------------- history


def test_history_filters_and_pagination(api: TestClient, shift_data: dict, use_provider) -> None:
    use_provider(json.dumps(valid_report()))
    production_record(
        api, product(api, "P-2")["id"], production_date="2026-01-09", shift="B",
        target_quantity=10, actual_quantity=10, accepted_quantity=10, rejected_quantity=0,
    )
    api.post(REPORTS, json=SHIFT)
    api.post(REPORTS, json={"production_date": "2026-01-09", "shift": "A"})
    api.post(REPORTS, json={"production_date": "2026-01-09", "shift": "B"})

    def query(**params: object) -> dict:
        response = api.get(REPORTS, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    assert query()["total"] == 3
    assert query(shift="B")["total"] == 1
    assert query(date_from="2026-01-10")["total"] == 1
    assert query(date_to="2026-01-09", shift="A")["total"] == 1
    assert query(status="failed")["total"] == 0
    page = query(limit=2, offset=2)
    assert page["total"] == 3 and len(page["items"]) == 1
    assert "metrics" not in page["items"][0]  # summaries only


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"date_from": "2026-01-10", "date_to": "2026-01-01"}, "invalid_date_range"),
        ({"status": "done"}, "validation_error"),
        ({"shift": "a b"}, "validation_error"),
    ],
)
def test_history_validation(api: TestClient, params: dict, code: str) -> None:
    response = api.get(REPORTS, params=params)
    assert response.status_code == 422
    assert error_code(response) == code


def test_unknown_report_is_404(api: TestClient) -> None:
    assert api.get(f"{REPORTS}/999").status_code == 404


def test_create_payload_is_validated(api: TestClient, use_provider) -> None:
    use_provider(json.dumps(valid_report()))
    for payload in (
        {**SHIFT, "unexpected": 1},
        {**SHIFT, "window_start": "2026-01-10T06:00:00Z"},
        {"shift": "A"},
    ):
        response = api.post(REPORTS, json=payload)
        assert response.status_code == 422
        assert error_code(response) == "validation_error"


# --------------------------------------------------------------------------- configuration


def test_provider_is_only_built_when_enabled_with_a_key() -> None:
    assert get_report_provider(make_settings()) is None
    assert get_report_provider(make_settings(ai_reports_enabled=True)) is None
    assert get_report_provider(make_settings(gemini_api_key="k")) is None  # not enabled
    provider = get_report_provider(
        make_settings(ai_reports_enabled=True, gemini_api_key="secret-key-123")
    )
    assert isinstance(provider, GeminiProvider)
    assert "secret-key-123" not in repr(provider)


def test_api_key_never_appears_in_settings_repr() -> None:
    settings = make_settings(ai_reports_enabled=True, gemini_api_key="secret-key-123")
    assert "secret-key-123" not in repr(settings)
    assert "secret-key-123" not in str(settings.model_dump())