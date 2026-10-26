# Module 3 — AI-Powered Shift Reports & Insights

Shift-level performance analysis computed deterministically from the database,
plus optional AI-written reports that interpret those figures, with history.

**Source of truth:** `app/services/shift_metrics.py`, a pure database read with no AI involvement.
The language model only writes the narrative. Every finding it makes must cite metric keys from the snapshot, and the server checks those keys.

## Shift definition and calculation rules

| Item | Rule |
|---|---|
| Shift | `production_date` (plant calendar day) + shift code. Production and quality use exactly those records; inspections count toward the record they inspect. |
| Target achievement | actual ÷ target |
| Rejection rate | rejected ÷ **actual output** |
| First-pass yield | accepted ÷ (accepted + rejected) |
| Defect rate | defects ÷ inspected units |
| Zero denominators | ratio is `null` ("not available"), never 0 |
| Downtime | Needs the shift window `[window_start, window_end)` (UTC, max 24 h). Each event counts only its overlap with the window; ongoing events count up to now. Plant-wide. Without a window: `available: false`. |
| Maintenance | `raised_in_window` = created inside the window. `open_now` = **current** open + in-progress backlog (status history is not stored, so the backlog at shift time cannot be reconstructed). |
| Previous comparable shift | Most recent earlier date with records for the same shift code (and data-source filter). Its downtime uses the same window moved back by the same number of days. Ratio changes are percentage points. |
| Limitations | Generated deterministically and listed in every snapshot (no window, no inspections, pending units, synthetic data, …). |

## API (`/api/v1`)

| Method & path | Purpose |
|---|---|
| `GET /shift-analysis?production_date&shift[&window_start&window_end&data_source]` | Deterministic metrics only (no AI) |
| `POST /shift-reports` body `{production_date, shift, window_start?, window_end?, data_source?, regenerate?}` | Generate a report. **201** new; **200** an existing report for identical data (unless `regenerate: true`) |
| `GET /shift-reports?date_from&date_to&shift&status&limit&offset` | History, newest first (summaries only) |
| `GET /shift-reports/{id}` | Full report: metrics snapshot, fingerprint, validated content |

Validation:
- **Window:** both ends or neither; it must end after it starts and last at most 24 h.
- **Timestamps:** must include a time zone.
- **Shift code:** must use the same format as production records.
- **Dates:** the date can't be in the future, and the window must start within a day of `production_date` (`window_date_mismatch`).

Errors use the standard envelope:

| HTTP | `code` | Meaning |
|---|---|---|
| 503 | `ai_not_configured` | AI disabled or no key (nothing is stored) |
| 409 | `report_in_progress` | Same shift already generating |
| 429 | `ai_rate_limited` | Provider rate limit |
| 504 | `ai_timeout` | Provider timeout |
| 502 | `ai_auth_failed`, `ai_request_rejected`, `ai_unavailable`, `ai_bad_response`, `ai_invalid_output` | Provider failures or output that failed validation |

Failed attempts are stored with `status: failed`, the safe error and the metrics snapshot. The error includes `details: [{"report_id": …}]`.

## Persistence (`shift_reports` table, migration `0003_shift_reports`)

Each report row stores:
- **Request:** date, shift, window and data-source filter.
- **Status:** `pending`, `completed` or `failed`.
- **Inputs:** `prompt_version`, the `metrics` snapshot (JSONB) and `input_fingerprint`, a SHA-256 of the request, prompt version and metrics.
- **Output:** the validated `content` (JSONB), provider and model.
- **Errors:** a safe error code and message.
- **Timestamps:** `created_at`, `updated_at` and `completed_at`.

Constraints:
- **Duplicates:** a partial unique index allows only one `pending` row per request. A concurrent duplicate gets a 409.
- **Abandoned attempts:** a `pending` row older than 5 minutes is marked `failed` (`ai_abandoned`).
- **Content:** a CHECK constraint requires `content` on completed rows.

The migration only creates this table; no existing table or row is changed. **Apply it yourself:** `alembic upgrade head`. Until you do, readiness reports the database as behind.

## AI provider (Gemini)

Configuration (`.env`, never committed):

    AI_REPORTS_ENABLED=false     # must be true to generate reports
    GEMINI_API_KEY=              # your key; stored as a secret, never logged or returned
    GEMINI_MODEL=gemini-2.5-flash
    AI_REQUEST_TIMEOUT_SECONDS=30

Implementation details:
- **Dependencies:** Python standard library only (`urllib`); nothing new to install.
- **Request:** HTTPS to `generativelanguage.googleapis.com`, with the key in the `x-goog-api-key` header (never in the URL), JSON output mode and temperature 0.2.
- **Response handling:** size-capped at 1 MB.
- **Logging:** only status, latency, model and token counts. Prompt and response text are never logged.

**What is sent:** the flattened metrics snapshot (`FACTS`), the deterministic limitations, and definitions. That means:
- totals and ratios;
- machine codes and defect category codes;
- up to 5 downtime reasons, truncated to 120 characters.

Production notes, inspection notes, maintenance issue descriptions, record ids and personal data are **not** sent.

**Output rules:**
- **Validation:** the output is checked against `AiShiftReport`. No extra fields are allowed, lengths and counts are capped, and every finding and recommendation needs at least one evidence key that exists in the snapshot.
- **Kinds:** each finding is a `measured_fact` or a `possible_explanation`.
- **Failures:** invalid output is rejected and stored as failed. It is never shown.

**Not checked automatically:** the server can't prove that every number written in a statement matches the metrics. The UI therefore shows each cited key next to its measured value, labels all content as AI-generated, and marks hypotheses. Reports must be reviewed by a person.

## Frontend

- **Navigation:** a new **Shift reports** page (`#/reports`) next to the Dashboard (`#/`), using hash routing with no new dependency.
- **Form:**
  - date defaults to the latest day with data;
  - shift code, with suggestions;
  - optional start and end times in local time (an end at or before the start means the next day);
  - data source, and a "regenerate" checkbox.
- **States:**
  - inputs are checked in the browser before any request;
  - the buttons are disabled while busy, with progress text during generation (up to 120 s);
  - each failure type has its own message, and a link opens the saved failed attempt.
- **Report view:**
  - "AI-generated content" label and a synthetic-data notice;
  - findings labelled "Measured fact" or "Possible explanation";
  - evidence shown as key = measured value, and recommendations by priority;
  - the AI's stated limitations, the data fingerprint, and the full measured metrics with the previous-shift comparison.
- **History:** filters for date range, shift and status, pagination, and a View button for each report.

## Verify locally

    cd backend
    .\.venv\Scripts\Activate.ps1
    ruff check .
    pytest -q
    alembic upgrade head        # applies 0003_shift_reports (your decision; dev database)
    cd ..\frontend
    npm test
    npm run build

To try real generation, set `AI_REPORTS_ENABLED=true` and `GEMINI_API_KEY` in your local `.env`, then restart uvicorn. This uses your Gemini quota, and the automated tests never call Gemini.

## Status and limitations

Implemented:
- [x] Deterministic metrics
- [x] Provider and prompt
- [x] Output validation
- [x] Persistence and duplicate prevention
- [x] API endpoints
- [x] UI
- [x] Backend and frontend tests

Not yet verified on the developer machine:
- [ ] Ruff, pytest, vitest and the vite build
- [ ] The migration on PostgreSQL
- [ ] A real Gemini call

Known limitations:
- **Shift windows:** must be entered manually; no shift schedule is stored.
- **Maintenance backlog:** the current backlog, not the backlog at shift time.
- **Numbers in AI text:** not checked against the metrics automatically; only the cited evidence keys are.
- **Request handling:** generation runs inside the request (no background queue). A long provider call holds one worker thread, but no database connection or lock.
- **Security:** no authentication yet (Module 0 scope), so anyone who can reach the API can generate reports and use quota.
- **Readiness:** not production-ready; there has been no deployment or security review.