# Module 2 — Manufacturing Intelligence Dashboard

A responsive dashboard over the Module 1 data: KPI cards, production and
quality trends, defect, downtime and maintenance summaries, and paginated
downtime and maintenance lists. All figures come from the backend; the
frontend has no hard-coded values and no sample records.

No database schema change and no migration: the head is still `0002_manufacturing_data`.
No new dependencies (backend or frontend).

## Backend: `GET /api/v1/analytics/dashboard` (read-only)

**Why a new endpoint:** the list endpoints return at most 200 rows per page,
and quality inspections cannot be filtered by machine, shift or product. KPIs
computed in the browser from those lists would be either truncated or would
need hundreds of requests. The new endpoint computes exact totals with SQL
`SUM`/`COUNT` in one database session and writes nothing.

| Query parameter | Meaning |
|---|---|
| `date_from`, `date_to` | Plant calendar dates, inclusive (`production_date`) |
| `shift`, `machine_id`, `product_id` | Same rules as `/production-records` |
| `data_source` | `manual` / `import` / `synthetic` — applies to every section |
| `utc_offset_minutes` | Plant UTC offset (−720…840, default 0) used to turn the date range into a UTC window for downtime and maintenance |

The response (`app/schemas/analytics.py`) contains raw totals only:
- **Overview:**
  - `production`: record count and target, actual, accepted, rejected and pending quantities.
  - `quality`: inspections, inspected quantity and defects. Inspections count toward the production date of the record they inspect.
- **Breakdowns:**
  - `trend`: one bucket per day, per ISO week (Monday start) for spans of 63–366 days, or per month above that.
  - `defects_by_category`, ranked.
- **Downtime:** each event's overlap with `[date_from 00:00, date_to+1 00:00)` in the plant offset. Ongoing events count until now. Machine-level, so shift and product filters do not apply.
- **Maintenance:**
  - the current backlog by status, and open/in-progress requests by priority (not date-filtered);
  - `raised_in_period`, the requests created in the window.
- **Context:**
  - `data_range`, the first and last production date ignoring the date filter;
  - `shifts` available for the shift filter;
  - `data_sources`, rows in scope per provenance, so synthetic data can be labelled.

Errors use the standard envelope: `invalid_date_range`, plus `validation_error` for a malformed date, an out-of-range offset, a bad shift code or id, or an unknown data source.

## Frontend

| Area | Files |
|---|---|
| Page | `src/pages/DashboardPage.jsx` (filters → requests → sections); `HomePage.jsx` renders it above the existing connectivity panel |
| API | `src/api/manufacturing.js` (dashboard summary, paginated lists, `fetchAllPages` for filter options), `src/api/query.js`; `client.js` gained a `params` option |
| Logic (pure, unit-tested) | `src/lib/kpi.js` (ratios), `dates.js` (calendar dates, presets, UTC offsets), `format.js`, `scale.js`, `errors.js` |
| Components | `components/ui/*` (Card, KpiCard, TrendChart, BarList, DataTable, Pagination, StateViews), `components/dashboard/*` |

KPI definitions (computed from totals, never from averaged daily ratios; `—` when the denominator is 0):

| KPI | Formula |
|---|---|
| Target achievement | actual ÷ target |
| First-pass yield | accepted ÷ (accepted + rejected) |
| Rejection rate | rejected ÷ actual |
| Defect rate | defects ÷ inspected units |
| Machine downtime | sum of event overlap with the period |
| Open maintenance | requests in `open` or `in_progress` |

Dates and time zones:
- **Calendar dates:** `YYYY-MM-DD` values are parsed as local calendar dates, never with `new Date(string)`, so they don't shift a day west of UTC.
- **Instants:** list filters such as `started_from` are sent as explicit UTC instants of local midnight.
- **Offset:** the browser's UTC offset on `date_from` is sent as `utc_offset_minutes`. The plant is assumed to be in the browser's time zone, and the page states the offset it used. For DST zones the offset of the first day is applied to the whole range.

States:
- **Loading:** skeletons and `aria-busy`.
- **Empty:** a region that offers the date range that does have data.
- **Invalid range:** checked in the browser; no request is sent.
- **API validation error:** a 422 is shown as "The filters were rejected".
- **Server, network and timeout failures:** shown with the request id and a retry button.
- **Filter options:** if they can't be loaded, the select is disabled and the figures still show.

Charts are dependency-free SVG:
- **Axes:** one y-axis per chart.
- **Interaction:** hover or arrow-key tooltip.
- **Accessibility:** a data table for every chart; legends and text labels, so colour is never the only cue.
- **Colour:** the palette passed a colour-vision-deficiency check in light and dark mode.

Synthetic data (Module 1 seed) is always labelled with a banner showing how many records in view are synthetic. Use **Data source → Manual entry** to see only real records.

## Verify locally

```powershell
cd backend
ruff check .
pytest -q                                   # includes tests/test_api_analytics.py

cd ..\frontend
npm test                                    # vitest
npm run build                               # vite production build

# manual check against the development database
cd ..\backend
uvicorn app.main:app --port 8000
Invoke-RestMethod "http://localhost:8000/api/v1/analytics/dashboard?utc_offset_minutes=330" | ConvertTo-Json -Depth 6
cd ..\frontend
npm run dev                                 # open http://localhost:5173
```

With the Module 1 synthetic seed loaded, "All dates" should show:
- 84 production records, with a daily trend for 2026-01-05 → 2026-01-18;
- 14 downtime events and 6 maintenance requests;
- the synthetic-data banner.

## Status

Implemented:
- [x] Analytics endpoint, service, schemas and backend tests
- [x] Dashboard UI, filters, states, charts, tables and frontend tests

Not yet verified on the developer machine:
- [ ] `ruff check .`, `pytest`, `npm test`, `npm run build`
- [ ] A manual check against the seeded development database

Not in scope: authentication, CSV/Excel import, exports, AI reports and agents (Module 3+).
Not production-ready: no deployment or security review has been done.