# FoundryOS AI — Architecture (Module 0)

This document describes the foundation delivered in Module 0 and the
conventions later modules must follow.

## 1. Components

```
 Browser
   │  React SPA (Vite)            frontend/src
   │   App → AppShell → HomePage
   │   useBackendStatus ─▶ api/health.js ─▶ api/client.js (fetch, timeout, error envelope)
   │
   │  HTTPS/JSON  GET /api/v1/health/live, /api/v1/health/ready
   ▼
 FastAPI application              backend/app
   CORSMiddleware                 (origins from CORS_ALLOWED_ORIGINS)
   RequestContextMiddleware       (request id, access log, unhandled → 500 envelope)
   Exception handlers             (AppError, HTTPException, validation → error envelope)
   api/routes/health.py           (thin HTTP layer)
     └─▶ services/health.py       (logic: DB ping + migration-state check)
           └─▶ db/session.py      (lazy SQLAlchemy engine, pooled, pre-ping)
   ▼
 PostgreSQL 16                    schema managed only by Alembic (backend/alembic)
```

### Backend layers

| Layer | Location | Responsibility | Rule |
|---|---|---|---|
| Configuration | `app/core/config.py` | Typed settings from env / `.env` | No secret defaults; invalid config fails fast at startup |
| Logging | `app/core/logging.py` | JSON or console logs with request id | Never log secrets, raw DB URLs, query strings or uploaded data |
| Errors | `app/core/errors.py` | Single error envelope; `AppError` hierarchy | Services raise `AppError` subclasses, never `HTTPException` |
| Middleware | `app/core/middleware.py` | Request id, access log, last-resort 500 | Pure ASGI (no BaseHTTPMiddleware) |
| Routes | `app/api/routes/*` | HTTP parsing, status codes, dependencies | No business logic, no SQL |
| Schemas | `app/schemas/*` | Pydantic request/response models | Every route declares `response_model` |
| Services | `app/services/*` | Business logic | Framework-agnostic; receive sessions/engines as arguments |
| Database | `app/db/*` | Base metadata, engine, sessions, model registry | Tables only via Alembic migrations |

### Frontend structure

| Folder | Responsibility |
|---|---|
| `config/` | Reads/validates `VITE_*` env vars; never throws — exposes `configError` |
| `api/` | `client.js` (fetch wrapper, timeout, `ApiError` kinds: config/network/timeout/http/parse) and one file per backend area |
| `hooks/` | Data fetching + state machines (`useBackendStatus`: loading / ready / not_ready / unreachable / misconfigured) |
| `components/` | Presentational, props-driven UI |
| `pages/` | Compose hooks and components per screen |

## 2. Data flow — connectivity check

1. `HomePage` mounts → `useBackendStatus` starts a check (cancellable via `AbortController`).
2. `GET /api/v1/health/live` — the process answers without touching the DB.
3. `GET /api/v1/health/ready` — the service opens a pooled connection, sets a
   2 s `statement_timeout`, runs `SELECT 1`, then compares the rows in
   `alembic_version` with the head revision(s) shipped in `alembic/versions`.
4. Response `200 ready` or `503 not_ready`, each with per-check status, latency and a safe detail message.
5. The UI renders Connected / Degraded / Offline / Not configured, with a re-check button.

## 3. API conventions

- All endpoints are under `/api/v1`. Breaking changes → `/api/v2`.
- Errors always use:
  ```json
  {"error": {"code": "not_found", "message": "…", "details": [...], "request_id": "…"}}
  ```
  `code` is stable and machine-readable; `details` is optional; validation
  details never echo the submitted input.
- Health endpoints are the exception: `/health/ready` returns its
  `ReadinessResponse` body for both 200 and 503 so probes and the UI can show which check failed.
- Every response carries `X-Request-ID` (incoming value reused if it matches `[A-Za-z0-9._-]{1,64}`).

## 4. Decisions

**D1 — Migrations only, no `create_all()`.** The API never creates tables. Schema
changes ship as reviewed Alembic revisions. Module 0 includes an empty
`0001_baseline` revision so the readiness probe can verify migrations were applied.

**D2 — Readiness verifies migration state, not just connectivity.** A reachable
database with a stale schema would make later modules fail at request time;
readiness reports 503 until `alembic upgrade head` has run.

**D3 — Liveness never touches the database.** Orchestrators restart unhealthy
processes on liveness failure; a database outage should mark the API *not ready*,
not trigger restart loops.

**D4 — Synchronous SQLAlchemy.** FastAPI runs sync endpoints in a thread pool.
Upcoming workloads (Pandas imports, report generation) are CPU/IO-mixed and
synchronous libraries; a sync stack avoids async/sync bridging complexity. Revisit
only if profiling shows thread-pool saturation.

**D5 — Frontend not containerised in Module 0.** Compose runs PostgreSQL, a
one-shot migration job and the API. The Vite dev server runs on the host for fast
HMR without bind-mount/file-watching issues. A production frontend image (static
build behind a web server) is planned for the deployment module.

**D6 — Single root `.env`.** Backend, Compose and Vite (`envDir: '..'`) share one
file. Vite exposes only `VITE_*` variables to the bundle; secrets must never use that prefix.

**D7 — CORS is explicit.** Origins come from `CORS_ALLOWED_ORIGINS`;
`allow_credentials=False` until authentication is designed. In `production`,
wildcards and non-https origins are rejected at startup.

**D8 — psycopg 3 driver.** Maintained, supports Python 3.13, binary wheels. URLs
are normalised to `postgresql+psycopg://`.

**D9 — Lazy engine creation.** Importing the app never opens a DB connection;
tests substitute engines through FastAPI dependency overrides.

**D10 — Dependency ranges + lock.** `requirements*.txt` and `package.json`
constrain to stable lines; exact locks (`requirements.lock`, `package-lock.json`)
are generated on first install and committed.

## 5. Security baseline

- Secrets only in environment variables; local `.env` files are git-ignored and are not included in the repository.
- `DATABASE_URL` excluded from `repr(Settings)`; logs use a password-masked URL.
- Readiness failures log only the exception class (driver messages can include host details) and return generic text.
- Unhandled exceptions return a generic 500 with request id; tracebacks stay in server logs.
- Compose binds PostgreSQL and the API to `127.0.0.1` only. API container runs as a non-root user.

## 6. Extension points for later modules

- New models: subclass `app.db.base.Base`, import them in `app/db/models.py`,
  then `alembic revision --autogenerate -m "..."` and review the output.
- New routers: `app/api/routes/<area>.py`, include in `app/api/router.py`.
- New business logic: `app/services/<area>.py`, raise `AppError` subclasses.
- Frontend: add `src/api/<area>.js`, a hook in `src/hooks/`, a page in `src/pages/`.
