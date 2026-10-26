# Module 1 — Manufacturing Data Foundation

Data model, API, migration and synthetic seed for production, quality,
downtime and maintenance data. No dashboards, analytics, AI or imports yet.

## Data model

```
machines ──< machine_downtime_events
   │    └──< maintenance_requests
   └──< production_records >── products
               └──< quality_inspections >── defect_categories
```

| Table | Purpose | Key rules (service layer **and** database) |
|---|---|---|
| `machines`, `products`, `defect_categories` | Master data | Unique business key (`code` / `part_number`), immutable once created; `is_active` instead of deletion |
| `production_records` | Output of one product (optionally on one machine) for a date + shift | Quantities ≥ 0; `accepted + rejected ≤ actual` (the remainder is `pending_quantity`, e.g. awaiting inspection); product (and machine) must exist and be active |
| `quality_inspections` | Inspection of a production record | `inspected > 0`; `defect ≤ inspected ≤ record.actual`; a defect category is required when `defect > 0`; one category per row |
| `machine_downtime_events` | Period a machine was down | `ended_at > started_at`; `status` derived (`ongoing` ⇔ no `ended_at`); no overlapping periods per machine; resolved events cannot be reopened |
| `maintenance_requests` | Maintenance work on a machine | Starts `open`; transitions below; `resolved`/`closed` require `resolution_notes` and set `resolved_at` |

Conventions:
- **Keys:** 64-bit surrogate primary keys. Foreign keys use `ON DELETE RESTRICT`, so there is no cascading data loss.
- **Timestamps:** every timestamp is UTC (`timestamptz`); naive datetimes are rejected at the API and in the database layer. `production_date` is the plant's calendar date.
- **Provenance:** every row has `data_source` = `manual` | `import` | `synthetic`. API clients cannot set it; API-created rows are `manual`.
- **External references:** fact tables have an optional, unique `external_ref` for idempotent imports and seeding.
- **No stored derived values:** downtime duration and pending quantity are computed when read.

### Maintenance status transitions

| From | Allowed to |
|---|---|
| `open` | `in_progress`, `cancelled` |
| `in_progress` | `open`, `resolved`, `cancelled` |
| `resolved` | `closed`, `in_progress` (reopen; clears `resolved_at`) |
| `closed`, `cancelled` | — (terminal; no further changes) |

## API (`/api/v1`)

Every resource supports `POST` (create, 201), `GET` (list), `GET /{id}` and `PATCH /{id}`
(partial update: only sent fields change; non-nullable fields cannot be set to `null`).
There is no `DELETE` (HTTP 405); master data is deactivated with `is_active=false`.

| Resource | List filters (all optional) |
|---|---|
| `/machines`, `/products`, `/defect-categories` | `is_active`, `q` (search key + name), `data_source` |
| `/production-records` | `date_from`, `date_to`, `shift`, `product_id`, `machine_id`, `data_source` |
| `/quality-inspections` | `inspected_from`, `inspected_to`, `production_record_id`, `defect_category_id`, `has_defects`, `data_source` |
| `/downtime-events` | `started_from`, `started_to`, `machine_id`, `status`, `data_source` |
| `/maintenance-requests` | `created_from`, `created_to`, `machine_id`, `status`, `priority`, `data_source` |

- **Pagination:** `limit` (1–200, default 50) and `offset`. Responses look like `{"items": [...], "total": N, "limit": L, "offset": O}`, newest first, with a stable tie-break on `id`.
- **Timestamp filters:** must include a timezone, e.g. `2026-01-10T00:00:00Z` (URL-encode `+` as `%2B`).

### Error codes (standard `{"error": {...}}` envelope)

| HTTP | `code` | When |
|---|---|---|
| 404 | `not_found` | Unknown id |
| 409 | `conflict` | Duplicate business key or `external_ref` |
| 409 | `overlapping_downtime` | Downtime overlaps another period of the same machine |
| 409 | `invalid_status_transition`, `request_closed` | Disallowed status change / terminal request |
| 422 | `validation_error` | Malformed input (types, ranges, unknown fields, naive timestamps) |
| 422 | `inconsistent_quantities` | Quantity rules above |
| 422 | `invalid_reference`, `inactive_reference` | Referenced row missing / inactive |
| 422 | `invalid_date_range` | `from` after `to`, or end not after start |
| 422 | `future_date`, `future_timestamp` | Dates/times in the future (5-minute clock-skew allowance) |
| 422 | `defect_category_required`, `resolution_notes_required` | Missing required companion field |

Database errors are never shown to clients; constraint failures surface as a generic 409.

## Migration

Revision `0002_manufacturing_data` builds on `0001_baseline`; `downgrade` drops only the Module 1 tables.
It is self-contained (it doesn't import the application models). Apply it deliberately:

```powershell
cd backend
alembic upgrade head              # creates the 7 tables (development database)
alembic downgrade 0001_baseline   # removes them again (destroys Module 1 data)
```

`tests/test_migrations.py` runs the migration on an in-memory SQLite database and
compares the result with the ORM models, so model/migration drift fails the test suite.

## Synthetic demonstration data

```powershell
cd backend
python -m app.cli.seed           # dry run: target database + dataset size, writes nothing
python -m app.cli.seed --apply   # insert missing synthetic rows (safe to repeat)
```

- **Labelling:** every row has `data_source = synthetic`; master keys start with `SYN-`; fact rows have an `external_ref` starting with `SYNTH-`; names and notes say "Synthetic".
- **Contents:** 4 machines, 3 products, 5 defect categories, 84 production records (14 days × 2 shifts × 3 products) with one inspection each, 14 downtime events and 6 maintenance requests covering every status (200 rows).
- **Deterministic:** the same dataset is generated every time; a re-run inserts nothing.
- **Safety:**
  - it never runs automatically and refuses when `ENVIRONMENT=production`;
  - it requires migrations to be at head;
  - it aborts without writing if a synthetic key already belongs to a non-synthetic row;
  - it runs in a single transaction.
- Use `data_source=manual` on any list endpoint to see only real data.

## Verification

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\scripts\verify_module1.ps1
```

This runs:
- the file presence check, `ruff`, `pytest`, `check_db` on both databases and `alembic current`;
- the integration tests against `foundryos_test`;
- API checks against a temporary server: readiness, every endpoint, the error envelopes and the absence of DELETE;
- a check that no `.env` file is tracked by git.

The development database is only read. No password is read or printed.

## Status

Implemented:
- [x] Normalised schema with FK, CHECK and unique constraints, indexes and UTC timestamps
- [x] Alembic revision `0002_manufacturing_data` (upgrade and downgrade)
- [x] Validated create/list/get/update endpoints with pagination and filters
- [x] Business rules in the service layer; one transaction per mutation; safe error envelopes
- [x] Idempotent, clearly labelled synthetic seed (dry run by default, refused in production)
- [x] Tests: schema constraints, UTC handling, relationships, migration vs. models, API CRUD,
      filters, pagination, failure cases, status transitions, seed idempotency

Verified on the developer machine (Windows, PostgreSQL 18.3, 2026-10-14):
- [x] `ruff check .` — all checks passed
- [x] `pytest` — 226 passed, 2 skipped (integration tests, run separately)
- [x] `pytest -m integration` against `foundryos_test` — 2 passed
- [x] `alembic upgrade head` on `foundryos` — at `0002_manufacturing_data (head)`
- [x] `scripts/check_db.py` on both databases — connected, privileges OK, migration applied
- [x] API against `foundryos`:
  - readiness `ready`;
  - all 7 list endpoints return the pagination envelope;
  - 404/422 error envelopes include a `request_id`;
  - DELETE returns 405.
- [x] `python -m app.cli.seed --apply` — 200 synthetic rows created; a second run created 0

Open items:
- [ ] Put the project under git and confirm no `.env` file is tracked
- [ ] `StarletteDeprecationWarning` from `fastapi.testclient` (httpx); this is a test-only warning, to be handled in a separate dependency review

Not verified and not claimed: production deployment, performance under load, authentication (not built yet).

Out of scope for Module 1 (later modules): CSV/Excel import, dashboards and
analytics, AI reports and agents, exports, authentication, deployment.