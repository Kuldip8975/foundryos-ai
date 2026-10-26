"""Synthetic demonstration data.

SYNTHETIC DATA ONLY. Nothing here describes a real company, machine, product
or production figure. Every row is stored with ``data_source='synthetic'``,
master-data keys start with ``SYN-``, fact rows carry an ``external_ref``
starting with ``SYNTH-``, and names/descriptions say "Synthetic".

Properties:
* deterministic — the same dataset is generated on every run (fixed RNG seed
  and fixed calendar window), independent of what is already stored;
* idempotent — rows are matched by business key / external_ref and only
  missing rows are inserted; a re-run creates nothing;
* safe — refuses to run in production, and aborts (without writing) if a
  synthetic key is already used by a non-synthetic row;
* atomic — one transaction; on any error nothing is written.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.enums import (
    DataSource,
    DowntimeStatus,
    MaintenancePriority,
    MaintenanceStatus,
)
from app.models.manufacturing import (
    DefectCategory,
    Machine,
    MachineDowntimeEvent,
    MaintenanceRequest,
    Product,
    ProductionRecord,
    QualityInspection,
)

SYNTHETIC = DataSource.SYNTHETIC.value
LABEL = "SYNTHETIC DEMO DATA - not real company data."
RNG_SEED = 20260105
FIRST_DAY = date(2026, 1, 5)
DAYS = 14
SHIFTS = {"A": time(6, 0), "B": time(18, 0)}  # synthetic shift start times, UTC

MACHINES = [
    ("SYN-CNC-01", "Synthetic CNC Mill 01"),
    ("SYN-CNC-02", "Synthetic CNC Mill 02"),
    ("SYN-PRS-01", "Synthetic Stamping Press 01"),
    ("SYN-ASM-01", "Synthetic Assembly Cell 01"),
]
PRODUCTS = [  # part number, name, machine code, nominal target per shift
    ("SYN-PART-1001", "Synthetic Bracket A", "SYN-CNC-01", 400),
    ("SYN-PART-1002", "Synthetic Housing B", "SYN-PRS-01", 250),
    ("SYN-PART-1003", "Synthetic Shaft C", "SYN-CNC-02", 300),
]
DEFECT_CATEGORIES = [
    ("SYN-DIM", "Synthetic: dimensional out of tolerance"),
    ("SYN-SURF", "Synthetic: surface finish defect"),
    ("SYN-BURR", "Synthetic: burr / sharp edge"),
    ("SYN-ASSY", "Synthetic: assembly fit issue"),
    ("SYN-MAT", "Synthetic: material flaw"),
]
DOWNTIME_REASONS = [
    "Synthetic: tool change",
    "Synthetic: material shortage",
    "Synthetic: unplanned stop - sensor fault",
    "Synthetic: changeover",
    "Synthetic: lubrication alarm",
]


class SeedRefusedError(RuntimeError):
    """The seed must not run in this environment or against this data."""


@dataclass
class SeedReport:
    created: dict[str, int] = field(default_factory=dict)
    existing: dict[str, int] = field(default_factory=dict)

    def record(self, table: str, *, created: bool) -> None:
        target = self.created if created else self.existing
        target[table] = target.get(table, 0) + 1

    @property
    def total_created(self) -> int:
        return sum(self.created.values())


def _at(day: date, clock: time, *, minutes: int = 0) -> datetime:
    return datetime.combine(day, clock, tzinfo=UTC) + timedelta(minutes=minutes)


# --------------------------------------------------------------------------- generation


def build_dataset() -> dict[str, list[dict[str, Any]]]:
    """The complete synthetic dataset as plain dicts (no database access)."""
    # Deterministic demo data, not security-sensitive: a seeded PRNG is intended.
    rng = random.Random(RNG_SEED)  # noqa: S311
    data: dict[str, list[dict[str, Any]]] = {
        "machines": [
            {"code": code, "name": name, "description": LABEL} for code, name in MACHINES
        ],
        "products": [
            {"part_number": part, "name": name, "description": LABEL}
            for part, name, _machine, _target in PRODUCTS
        ],
        "defect_categories": [
            {"code": code, "name": name, "description": LABEL} for code, name in DEFECT_CATEGORIES
        ],
        "production_records": [],
        "quality_inspections": [],
        "machine_downtime_events": [],
        "maintenance_requests": [],
    }
    defect_codes = [code for code, _ in DEFECT_CATEGORIES]

    for offset in range(DAYS):
        day = FIRST_DAY + timedelta(days=offset)
        for shift, start in SHIFTS.items():
            for part, _name, machine, nominal in PRODUCTS:
                actual = int(nominal * rng.uniform(0.82, 1.03))
                rejected = int(actual * rng.uniform(0.005, 0.04))
                pending = rng.randint(0, 10) if offset == DAYS - 1 else 0
                ref = f"SYNTH-PR-{day:%Y%m%d}-{shift}-{part}"
                data["production_records"].append(
                    {
                        "external_ref": ref,
                        "production_date": day,
                        "shift": shift,
                        "product": part,
                        "machine": machine,
                        "target_quantity": nominal,
                        "actual_quantity": actual,
                        "accepted_quantity": actual - rejected - pending,
                        "rejected_quantity": rejected,
                        "notes": LABEL,
                    }
                )
                inspected = min(actual, rng.randint(40, 80))
                defects = rng.randint(0, inspected // 10)
                data["quality_inspections"].append(
                    {
                        "external_ref": f"SYNTH-QI-{day:%Y%m%d}-{shift}-{part}",
                        "production_record": ref,
                        "inspected_at": _at(day, start, minutes=rng.randint(240, 600)),
                        "inspected_quantity": inspected,
                        "defect_quantity": defects,
                        "defect_category": rng.choice(defect_codes) if defects else None,
                        "notes": LABEL,
                    }
                )

    # At most one downtime event per machine per day, always within that day:
    # events for the same machine can never overlap.
    for code, _name in MACHINES:
        for offset in range(DAYS):
            if rng.random() >= 0.3:
                continue
            day = FIRST_DAY + timedelta(days=offset)
            started = _at(day, time(0, 0), minutes=rng.randint(0, 20 * 60))
            data["machine_downtime_events"].append(
                {
                    "external_ref": f"SYNTH-DT-{code}-{day:%Y%m%d}",
                    "machine": code,
                    "started_at": started,
                    "ended_at": started + timedelta(minutes=rng.randint(15, 180)),
                    "status": DowntimeStatus.RESOLVED.value,
                    "reason": rng.choice(DOWNTIME_REASONS),
                    "notes": LABEL,
                }
            )

    requests = [
        ("SYN-CNC-01", "Synthetic: spindle vibration above normal", "high", "open", None),
        ("SYN-PRS-01", "Synthetic: hydraulic pressure drifting", "medium", "in_progress", None),
        ("SYN-CNC-02", "Synthetic: coolant leak at enclosure", "high", "resolved",
         "Synthetic: replaced coolant line seal."),
        ("SYN-ASM-01", "Synthetic: torque tool calibration due", "low", "closed",
         "Synthetic: calibrated and verified."),
        ("SYN-CNC-01", "Synthetic: request raised in error", "low", "cancelled", None),
        ("SYN-PRS-01", "Synthetic: guard interlock intermittent", "critical", "open", None),
    ]
    for index, (machine, issue, priority, status, resolution) in enumerate(requests, start=1):
        created = _at(FIRST_DAY + timedelta(days=index * 2), time(8, 0))
        resolved = status in ("resolved", "closed")
        data["maintenance_requests"].append(
            {
                "external_ref": f"SYNTH-MR-{index:03d}",
                "machine": machine,
                "issue_description": issue,
                "priority": MaintenancePriority(priority).value,
                "status": MaintenanceStatus(status).value,
                "resolution_notes": resolution,
                "resolved_at": created + timedelta(days=1) if resolved else None,
                "created_at": created,
                "updated_at": created + timedelta(days=1) if resolved else created,
            }
        )
    return data


# --------------------------------------------------------------------------- persistence


def _ensure_synthetic(entity: Any, key: str) -> None:
    if entity.data_source != SYNTHETIC:
        raise SeedRefusedError(
            f"Key {key!r} already belongs to a non-synthetic record; refusing to seed. "
            "Synthetic data must never be mixed into real records."
        )


def _upsert_master(
    db: Session, report: SeedReport, model: Any, key_attr: str, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    key_column = getattr(model, key_attr)
    keys = [row[key_attr] for row in rows]
    found = {getattr(e, key_attr): e for e in db.scalars(select(model).where(key_column.in_(keys)))}
    by_key: dict[str, Any] = {}
    for row in rows:
        key = row[key_attr]
        entity = found.get(key)
        if entity is None:
            entity = model(**row, data_source=SYNTHETIC)
            db.add(entity)
            report.record(model.__tablename__, created=True)
        else:
            _ensure_synthetic(entity, key)
            report.record(model.__tablename__, created=False)
        by_key[key] = entity
    db.flush()
    return by_key


def _upsert_facts(
    db: Session, report: SeedReport, model: Any, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    refs = [row["external_ref"] for row in rows]
    stmt = select(model).where(model.external_ref.in_(refs))
    found = {e.external_ref: e for e in db.scalars(stmt)}
    by_ref: dict[str, Any] = {}
    for row in rows:
        entity = found.get(row["external_ref"])
        if entity is None:
            entity = model(**row, data_source=SYNTHETIC)
            db.add(entity)
            report.record(model.__tablename__, created=True)
        else:
            _ensure_synthetic(entity, row["external_ref"])
            report.record(model.__tablename__, created=False)
        by_ref[row["external_ref"]] = entity
    db.flush()
    return by_ref


def seed_synthetic_data(db: Session, settings: Settings) -> SeedReport:
    """Insert the synthetic dataset; return what was created vs. already present."""
    if settings.is_production:
        raise SeedRefusedError("Synthetic data must never be loaded in production.")

    data = build_dataset()
    report = SeedReport()
    try:
        machines = _upsert_master(db, report, Machine, "code", data["machines"])
        products = _upsert_master(db, report, Product, "part_number", data["products"])
        categories = _upsert_master(
            db, report, DefectCategory, "code", data["defect_categories"]
        )

        production = _upsert_facts(
            db, report, ProductionRecord,
            [
                {
                    **{k: v for k, v in row.items() if k not in ("product", "machine")},
                    "product_id": products[row["product"]].id,
                    "machine_id": machines[row["machine"]].id,
                }
                for row in data["production_records"]
            ],
        )
        _upsert_facts(
            db, report, QualityInspection,
            [
                {
                    **{
                        k: v for k, v in row.items()
                        if k not in ("production_record", "defect_category")
                    },
                    "production_record_id": production[row["production_record"]].id,
                    "defect_category_id": (
                        categories[row["defect_category"]].id if row["defect_category"] else None
                    ),
                }
                for row in data["quality_inspections"]
            ],
        )
        for table_model, rows in (
            (MachineDowntimeEvent, data["machine_downtime_events"]),
            (MaintenanceRequest, data["maintenance_requests"]),
        ):
            _upsert_facts(
                db, report, table_model,
                [
                    {
                        **{k: v for k, v in row.items() if k != "machine"},
                        "machine_id": machines[row["machine"]].id,
                    }
                    for row in rows
                ],
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return report