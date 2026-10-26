"""Synthetic seed: idempotent, clearly labelled, never in production."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cli import seed as seed_cli
from app.models.manufacturing import (
    DefectCategory,
    Machine,
    MachineDowntimeEvent,
    MaintenanceRequest,
    Product,
    ProductionRecord,
    QualityInspection,
)
from app.services.seed import SeedRefusedError, build_dataset, seed_synthetic_data
from tests.conftest import make_settings

MODELS = [
    Machine,
    Product,
    DefectCategory,
    ProductionRecord,
    QualityInspection,
    MachineDowntimeEvent,
    MaintenanceRequest,
]


def _counts(db: Session) -> dict[str, int]:
    return {m.__tablename__: db.scalar(select(func.count()).select_from(m)) for m in MODELS}


def test_dataset_is_deterministic_and_non_trivial() -> None:
    first, second = build_dataset(), build_dataset()
    assert first == second
    assert len(first["production_records"]) == 14 * 2 * 3
    assert len(first["quality_inspections"]) == len(first["production_records"])
    assert first["machine_downtime_events"]
    assert {r["status"] for r in first["maintenance_requests"]} == {
        "open", "in_progress", "resolved", "closed", "cancelled",
    }


def test_seed_inserts_everything_labelled_synthetic(db_session: Session) -> None:
    report = seed_synthetic_data(db_session, make_settings())
    expected = {table: len(rows) for table, rows in build_dataset().items()}
    assert report.created == expected
    assert report.existing == {}
    assert _counts(db_session) == expected

    for model in MODELS:
        sources = set(db_session.scalars(select(model.data_source)))
        assert sources == {"synthetic"}, model.__tablename__
    assert all(code.startswith("SYN-") for code in db_session.scalars(select(Machine.code)))
    refs = db_session.scalars(select(ProductionRecord.external_ref))
    assert all(ref.startswith("SYNTH-") for ref in refs)
    assert all("Synthetic" in name for name in db_session.scalars(select(Product.name)))


def test_seed_is_idempotent(db_session: Session) -> None:
    seed_synthetic_data(db_session, make_settings())
    before = _counts(db_session)

    second = seed_synthetic_data(db_session, make_settings())
    assert second.total_created == 0
    assert second.existing == before
    assert _counts(db_session) == before


def test_seeded_data_respects_business_rules(db_session: Session) -> None:
    seed_synthetic_data(db_session, make_settings())
    for record in db_session.scalars(select(ProductionRecord)):
        assert record.accepted_quantity + record.rejected_quantity <= record.actual_quantity
        for inspection in record.inspections:
            assert inspection.inspected_quantity <= record.actual_quantity

    by_machine: dict[int, list[MachineDowntimeEvent]] = {}
    for event in db_session.scalars(select(MachineDowntimeEvent)):
        by_machine.setdefault(event.machine_id, []).append(event)
    for events in by_machine.values():
        events.sort(key=lambda e: e.started_at)
        for earlier, later in zip(events, events[1:], strict=False):
            assert earlier.ended_at is not None and earlier.ended_at <= later.started_at


def test_seed_refuses_production(db_session: Session) -> None:
    production = make_settings(
        environment="production", cors_allowed_origins="https://foundryos.example"
    )
    with pytest.raises(SeedRefusedError):
        seed_synthetic_data(db_session, production)
    assert sum(_counts(db_session).values()) == 0


def test_seed_never_mixes_into_real_records(db_session: Session) -> None:
    db_session.add(Machine(code="SYN-CNC-01", name="A real machine", data_source="manual"))
    db_session.commit()

    with pytest.raises(SeedRefusedError, match="non-synthetic"):
        seed_synthetic_data(db_session, make_settings())

    counts = _counts(db_session)
    assert counts["machines"] == 1  # only the real row; the failed seed was rolled back
    assert counts["products"] == 0
    assert counts["production_records"] == 0


def test_cli_dry_run_writes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    # The dry run never creates an engine, so no database is contacted.
    assert seed_cli.main([]) == seed_cli.EXIT_OK
    out = capsys.readouterr().out
    assert "SYNTHETIC" in out
    assert "Dry run" in out
    assert "placeholder@" not in out  # credentials are never printed


def test_cli_refuses_production(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    production = make_settings(
        environment="production", cors_allowed_origins="https://foundryos.example"
    )
    monkeypatch.setattr(seed_cli, "get_settings", lambda: production)
    assert seed_cli.main(["--apply"]) == seed_cli.EXIT_REFUSED
    assert "REFUSED" in capsys.readouterr().out