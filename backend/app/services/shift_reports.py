"""AI shift report generation, persistence and history (Module 3).

Flow for ``generate_shift_report``:

1. compute deterministic metrics (read-only) and their SHA-256 fingerprint;
2. if a completed report for the same request and identical data exists,
   return it instead of calling the provider again (unless ``regenerate``);
3. insert a ``pending`` row and commit. A partial unique index allows only one
   pending row per request key, so a concurrent duplicate fails with 409;
4. call the provider **outside** any open transaction (no locks held);
5. validate the output against :class:`AiShiftReport`, with every evidence key
   checked against the metrics snapshot;
6. store ``completed`` (with content) or ``failed`` (with a safe error code).

Manufacturing records are only ever read.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, BusinessRuleError, ConflictError
from app.models.enums import ReportStatus
from app.models.reports import ShiftReport
from app.schemas.shift_reports import AiShiftReport, ShiftScopeIn
from app.services.ai_provider import (
    Prompt,
    ProviderError,
    ReportProvider,
    invalid_output,
    not_configured,
)
from app.services.common import (
    ensure_date_not_future,
    ensure_not_future,
    get_or_404,
    paginate,
    validate_range,
)
from app.services.shift_metrics import ShiftScope, compute_shift_metrics, flatten_metrics

logger = logging.getLogger(__name__)

PROMPT_VERSION = "shift-report-v1"
# A pending row older than this is treated as abandoned (e.g. the server stopped
# mid-generation) so it cannot block new requests forever.
STALE_PENDING_AFTER = timedelta(minutes=5)
MAX_WINDOW_DATE_DISTANCE = timedelta(days=1)


# --------------------------------------------------------------------------- scope


def to_scope(data: ShiftScopeIn) -> ShiftScope:
    """Validated request → scope, with checks that need the current time."""
    ensure_date_not_future(data.production_date, field="production_date")
    if data.window_start is not None and data.window_end is not None:
        ensure_not_future(data.window_start, field="window_start")
        window_day = data.window_start.astimezone(UTC).date()
        if abs(window_day - data.production_date) > MAX_WINDOW_DATE_DISTANCE:
            raise BusinessRuleError(
                "The shift window must start within one day of production_date",
                code="window_date_mismatch",
                details=[{"field": "window_start"}],
            )
    return ShiftScope(
        production_date=data.production_date,
        shift=data.shift,
        window_start=data.window_start.astimezone(UTC) if data.window_start else None,
        window_end=data.window_end.astimezone(UTC) if data.window_end else None,
        data_source=data.data_source,
    )


def analyse_shift(db: Session, data: ShiftScopeIn) -> dict[str, Any]:
    return compute_shift_metrics(db, to_scope(data))


def request_key(scope: ShiftScope) -> str:
    parts = [
        scope.production_date.isoformat(),
        scope.shift,
        scope.window_start.isoformat() if scope.window_start else "-",
        scope.window_end.isoformat() if scope.window_end else "-",
        scope.data_source.value if scope.data_source else "all",
    ]
    return "|".join(parts)


def fingerprint(metrics: dict[str, Any], key: str) -> str:
    canonical = json.dumps(
        {"request": key, "prompt_version": PROMPT_VERSION, "metrics": metrics},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- prompt + validation

SYSTEM_PROMPT = """You write shift performance reports for a manufacturing plant.

Rules you must follow:
1. The FACTS object is the only source of numbers. Never invent, estimate or
   recalculate metrics, events, machines, causes or people. Do not round
   differently from FACTS, except that ratios (fractions between 0 and 1) may be
   written as percentages with one decimal (0.0453 -> 4.5%).
2. Every finding and recommendation must cite one or more FACTS keys in its
   "evidence" array, copied exactly. Cite only keys that exist in FACTS.
3. kind "measured_fact" only restates what FACTS show. Anything about causes is
   kind "possible_explanation" and must be worded as a possibility ("may",
   "could"), never as established fact. Do not claim causal relationships the
   data cannot show.
4. If a value is null or missing, say it is not available; do not guess.
5. Mention every item in LIMITATIONS that affects the conclusions, in
   data_limitations. If FACTS include synthetic data, say so in the summary.
6. Recommendations must be practical follow-ups (investigate, verify, check),
   ordered high > medium > low priority. Never instruct anyone to change
   production records.
7. Reply with one JSON object only, exactly in this shape (no extra keys):
{"executive_summary": string,
 "production_performance": [Finding],
 "quality_observations": [Finding],
 "downtime_maintenance_observations": [Finding],
 "recommendations": [{"priority": "high"|"medium"|"low", "action": string,
                      "rationale": string, "evidence": [FACTS key, ...]}],
 "data_limitations": [string]}
where Finding = {"statement": string,
                 "kind": "measured_fact"|"possible_explanation",
                 "evidence": [FACTS key, ...]}.
Use at most 8 findings per list, 6 recommendations and 10 limitations."""


def build_prompt(metrics: dict[str, Any]) -> Prompt:
    """Only aggregated metrics are sent: no notes, issue descriptions or ids."""
    facts = {k: v for k, v in flatten_metrics(metrics).items() if not k.startswith("limitations")}
    payload = {
        "SHIFT": {
            "production_date": metrics["production_date"],
            "shift": metrics["shift"],
            "window_start_utc": metrics["window_start"],
            "window_end_utc": metrics["window_end"],
        },
        "FACTS": facts,
        "LIMITATIONS": metrics["limitations"],
        "DEFINITIONS": {
            "target_achievement": "actual / target",
            "rejection_rate": "rejected / actual",
            "first_pass_yield": "accepted / (accepted + rejected)",
            "defect_rate": "defects / inspected units",
            "comparison.*": "this shift minus the previous shift with the same code",
            "maintenance.open_now": "current backlog, not as of the shift",
        },
    }
    return Prompt(system=SYSTEM_PROMPT, user=json.dumps(payload, ensure_ascii=False, indent=1))


def parse_report(text: str, metrics: dict[str, Any]) -> AiShiftReport:
    """Validate raw model output. Raises ``ai_invalid_output`` (never echoes the text)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise invalid_output("It was not valid JSON.") from None
    allowed = set(flatten_metrics(metrics))
    try:
        return AiShiftReport.model_validate(data, context={"allowed_evidence": allowed})
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        logger.info("ai output rejected", extra={"error_count": exc.error_count()})
        raise invalid_output(f"First problem at '{location or 'root'}'.") from None


# --------------------------------------------------------------------------- generation


@dataclass(frozen=True)
class GenerationResult:
    report: ShiftReport
    created: bool  # False when an existing report for identical data was returned


def _expire_stale_pending(db: Session, key: str, now: datetime) -> None:
    stale = db.scalars(
        select(ShiftReport).where(
            ShiftReport.request_key == key,
            ShiftReport.status == ReportStatus.PENDING.value,
            ShiftReport.created_at < now - STALE_PENDING_AFTER,
        )
    ).all()
    for report in stale:
        report.status = ReportStatus.FAILED.value
        report.error_code = "ai_abandoned"
        report.error_message = "Generation did not finish and was abandoned."
        report.completed_at = now
    if stale:
        db.commit()


def _finish_failed(db: Session, report: ShiftReport, error: ProviderError) -> None:
    report.status = ReportStatus.FAILED.value
    report.error_code = error.code
    report.error_message = error.message[:300]
    report.completed_at = datetime.now(UTC)
    db.commit()


def generate_shift_report(
    db: Session,
    data: ShiftScopeIn,
    *,
    provider: ReportProvider | None,
    regenerate: bool = False,
    now: datetime | None = None,
) -> GenerationResult:
    if provider is None:
        raise _as_app_error(not_configured())
    now = now or datetime.now(UTC)
    scope = to_scope(data)
    metrics = compute_shift_metrics(db, scope, now=now)
    key = request_key(scope)
    digest = fingerprint(metrics, key)

    _expire_stale_pending(db, key, now)
    if not regenerate:
        existing = db.scalars(
            select(ShiftReport)
            .where(
                ShiftReport.request_key == key,
                ShiftReport.input_fingerprint == digest,
                ShiftReport.status == ReportStatus.COMPLETED.value,
                ShiftReport.model == provider.model,
            )
            .order_by(ShiftReport.id.desc())
            .limit(1)
        ).first()
        if existing is not None:
            return GenerationResult(report=existing, created=False)

    report = ShiftReport(
        request_key=key,
        production_date=scope.production_date,
        shift=scope.shift,
        window_start=scope.window_start,
        window_end=scope.window_end,
        data_source=scope.data_source.value if scope.data_source else None,
        status=ReportStatus.PENDING.value,
        prompt_version=PROMPT_VERSION,
        input_fingerprint=digest,
        metrics=metrics,
        provider=provider.name,
        model=provider.model,
    )
    db.add(report)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError(
            "A report for this shift is already being generated. Try again shortly.",
            code="report_in_progress",
        ) from None
    db.refresh(report)

    try:
        result = provider.generate(build_prompt(metrics))
        content = parse_report(result.text, metrics)
    except ProviderError as error:
        _finish_failed(db, report, error)
        raise _as_app_error(error, report_id=report.id) from None
    except Exception:
        logger.exception("unexpected error during report generation")
        _finish_failed(
            db, report, ProviderError("ai_internal_error", "Report generation failed.", 500)
        )
        raise

    report.status = ReportStatus.COMPLETED.value
    report.content = content.model_dump(mode="json")
    report.model = result.model
    report.completed_at = datetime.now(UTC)
    db.commit()
    db.refresh(report)
    return GenerationResult(report=report, created=True)


def _as_app_error(error: ProviderError, report_id: int | None = None) -> AppError:
    details = [{"report_id": report_id}] if report_id is not None else None
    return AppError(error.message, code=error.code, status_code=error.http_status, details=details)


# --------------------------------------------------------------------------- history


@dataclass(frozen=True)
class ReportFilters:
    date_from: date | None = None
    date_to: date | None = None
    shift: str | None = None
    status: ReportStatus | None = None


def list_reports(
    db: Session, filters: ReportFilters, *, limit: int, offset: int
) -> tuple[list[ShiftReport], int]:
    validate_range(filters.date_from, filters.date_to, start_field="date_from", end_field="date_to")
    stmt = select(ShiftReport)
    if filters.date_from is not None:
        stmt = stmt.where(ShiftReport.production_date >= filters.date_from)
    if filters.date_to is not None:
        stmt = stmt.where(ShiftReport.production_date <= filters.date_to)
    if filters.shift is not None:
        stmt = stmt.where(ShiftReport.shift == filters.shift)
    if filters.status is not None:
        stmt = stmt.where(ShiftReport.status == filters.status.value)
    order = (ShiftReport.created_at.desc(), ShiftReport.id.desc())
    return paginate(db, stmt, order_by=order, limit=limit, offset=offset)


def get_report(db: Session, report_id: int) -> ShiftReport:
    return get_or_404(db, ShiftReport, report_id, "Shift report")