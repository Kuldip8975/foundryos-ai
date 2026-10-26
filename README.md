# FoundryOS AI

**Manufacturing intelligence and controlled workflow automation for the shop floor.**

FoundryOS AI turns the data operators already record — downtime, output, rejects,
inspections and maintenance — into live plant KPIs, AI-written shift reports and
maintenance requests. AI prepares the work; people approve it; every action is
recorded.

> **Project status:** Modules 0–5 are complete and verified on a local installation
> (backend: Ruff clean, 487 automated tests; frontend: Vitest suite and production
> build). The system currently runs against a clearly labelled **synthetic** demo
> dataset and has **not yet been deployed or used in a production plant**.

---

## Contents

1. [The problem](#1-the-problem)
2. [The solution](#2-the-solution)
3. [Problem → solution mapping](#3-problem--solution-mapping)
4. [Key capabilities](#4-key-capabilities)
5. [Roles and access](#5-roles-and-access)
6. [How it works](#6-how-it-works)
7. [Architecture](#7-architecture)
8. [Security and data governance](#8-security-and-data-governance)
9. [Responsible AI](#9-responsible-ai)
10. [Technology stack](#10-technology-stack)
11. [Getting started](#11-getting-started)
12. [Testing and quality](#12-testing-and-quality)
13. [Configuration reference](#13-configuration-reference)
14. [Project structure](#14-project-structure)
15. [Documentation](#15-documentation)
16. [Limitations and roadmap](#16-limitations-and-roadmap)

---

## 1. The problem

Small and mid-sized manufacturers — machine shops, foundries, stamping and
assembly plants — run on data that is captured late, scattered and hard to trust.

| Today's reality on the shop floor | Business impact |
|---|---|
| **Downtime is recorded on paper, WhatsApp or Excel**, often at the end of the shift, from memory | Real causes of lost capacity stay invisible; the same failures repeat |
| **KPIs are calculated by hand** (output vs target, rejection %, yield, downtime) | Supervisors lose 1–2 hours per shift on spreadsheets instead of the floor; numbers differ between people |
| **Shift reports are written manually** and vary in quality | Management decisions rely on opinion, not on consistent evidence |
| **Answers need someone to dig through records** ("Why does CNC-02 keep stopping?") | Slow root-cause analysis; problems are noticed only after they become expensive |
| **Maintenance requests are informal** — verbal, chat messages, paper slips | Requests get lost or duplicated; no record of who asked, who approved, when |
| **Everyone can see or change everything** in shared files | No accountability, no audit trail, risk of accidental or deliberate data changes |
| **Fear of AI in operations** — "What if it changes something on its own?" | Plants avoid AI entirely and miss its benefits |

## 2. The solution

FoundryOS AI is a private, role-based web application for the plant:

- **Operators** record downtime and shift output in seconds — only for the machines
  assigned to them.
- **The system** calculates KPIs, trends and breakdowns automatically from those records.
- **AI** writes shift reports and answers questions **only from measured plant data**,
  citing the evidence behind every statement.
- **The AI assistant prepares** maintenance requests, but **nothing is created until
  a supervisor reviews and approves** the exact action.
- **Admins** control who can access what; every sign-in, change and approval is
  **audited**.

In short: **people record, the system calculates, the AI prepares, supervisors approve.**

## 3. Problem → solution mapping

| Problem | How FoundryOS AI solves it | Outcome |
|---|---|---|
| Late, scattered downtime records | Operator page to record downtime with start, end and reason, validated at entry (no overlaps, no future times) | One reliable source of downtime data, recorded when it happens |
| Manual KPI calculation | Dashboard computes output, target achievement, first-pass yield, rejection and defect rates, downtime by machine and maintenance backlog with consistent, documented definitions | Supervisor time returned to the floor; everyone sees the same numbers |
| Manual, inconsistent shift reports | Deterministic shift metrics, then an AI report generated **only** from those metrics; every finding cites the figure it is based on; output is validated before it is stored | Consistent, traceable reports in seconds |
| Slow root-cause analysis | Workflow assistant answers plain-language questions using a fixed set of read-only, allowlisted tools; each answer cites its evidence | Faster investigation without database skills |
| Informal maintenance requests | Assistant prepares a request → supervisor reviews and approves → request is created; approval is bound to the exact action (hash), idempotent and time-limited | No lost requests; clear ownership and history |
| No access control or accountability | Private accounts, four roles, per-machine scope for operators, expiring sessions, account lockout, full access and workflow audit logs | Accountability and readiness for quality/ISO audits |
| Fear of AI acting on its own | AI never writes data; it only proposes. Separation of duties: the person who prepared an action cannot approve it | Safe, controllable adoption of AI |
| Reports needed on paper | **Download PDF** for shift reports, the dashboard and the access log | Ready for meetings and audits |

## 4. Key capabilities

| Area | Capabilities |
|---|---|
| **Manufacturing data** (Module 1) | Machines, products, defect categories, production records, quality inspections, downtime events, maintenance requests; validation in the API **and** database constraints; provenance on every row (manual / import / synthetic) |
| **Dashboard** (Module 2) | KPI cards, production and defect-rate trends, downtime by machine, defects by category, maintenance backlog, paginated event tables; filters by period, shift, machine, product and data source |
| **AI shift reports** (Module 3) | Deterministic metrics per shift, comparison with the previous shift, AI narrative with cited evidence, schema-validated output, report history, duplicate-generation protection |
| **Workflow assistant** (Module 4) | Natural-language questions, allowlisted read-only tools with limits, evidence-cited answers, maintenance-request proposals with human approval, full step-by-step audit trail |
| **Accounts and access** (Module 5) | Admin-only provisioning (no public sign-up), admin-chosen or one-time passwords, forced password change option, role start pages, deactivation, password reset, access log |
| **Operator workspace** | Live state of assigned machines, downtime and shift-output entry forms, own records and maintenance status |
| **Usability** | Sign-in page with an embedded product walkthrough video; PDF export; responsive layout down to phone width; keyboard-accessible controls |

## 5. Roles and access

| Role | Start page | Permitted | Not permitted |
|---|---|---|---|
| **Operator** | My machines | Record downtime, output and inspections for **assigned machines only**; view own machines' records; ask the assistant; prepare maintenance requests | Other machines, plant-wide analytics, approvals, user management |
| **Supervisor** | Dashboard | Plant-wide dashboard and shift reports; record data; manage maintenance; **approve or reject** AI-prepared actions | User management, access log |
| **Production manager** | Dashboard | Analytics and reports; machine/product master data; read-only assistant | Recording data, approvals, user management |
| **Admin** | Users & access | Create accounts, set roles, passwords and machine assignments; deactivate accounts; read the access log | Production data, approvals |

Permissions are fixed in backend code and checked on **every** API request.
A role sent by the browser is never trusted; the interface only hides what the
server would refuse anyway.

## 6. How it works

```
 Operator                     FoundryOS AI backend                       Supervisor / Manager
 ────────                     ────────────────────                       ────────────────────
 records downtime  ──────▶  validate + store (PostgreSQL)  ──────▶  dashboard KPIs, trends
 records output              │                                       shift metrics
                             ▼
                      deterministic metrics ──▶ AI (Gemini) ──▶ validated shift report
                                                                  with cited evidence

 asks the assistant ──▶  allowlisted read-only tools ──▶ answer + evidence
 "raise maintenance"     prepare_maintenance_request ──▶ PROPOSAL (nothing written)
                                                              │
                                              supervisor reviews and approves
                                                              ▼
                                   maintenance request created in one transaction
                                   + audit events (who, what, when)
```

## 7. Architecture

| Layer | Responsibility |
|---|---|
| **React web client** | Sign-in, role-based navigation, dashboards, forms, PDF export. Holds only a session token (per browser tab). |
| **FastAPI service** | Versioned REST API (`/api/v1`), authentication and per-endpoint authorisation, validation, business rules, AI orchestration, audit logging |
| **PostgreSQL** | Single source of truth; schema managed by Alembic migrations (`0001`–`0005`); constraints mirror business rules |
| **AI provider (optional)** | Google Gemini, called only with aggregated, minimal data; disabled unless explicitly enabled |

Design principles: business rules enforced twice (service layer and database),
consistent error envelope with request IDs, structured logging, lazy database
connections, health and readiness endpoints for operations.
Details: [`docs/architecture.md`](docs/architecture.md).

## 8. Security and data governance

- **Private by design:** no public sign-up; only an admin (or a one-time command-line bootstrap) creates accounts. There are no default credentials.
- **Passwords:** salted **scrypt** hashes (OWASP parameters); minimum length and common-password rules; never logged or returned.
- **Sessions:** random 256-bit tokens, stored only as SHA-256 hashes; expire after 8 hours or 30 minutes of inactivity; revoked on sign-out, deactivation and password reset.
- **Brute-force protection:** account lockout after repeated failures, rate limiting per client and username, identical responses for all sign-in failures.
- **Least privilege:** four roles, per-endpoint permissions, per-machine data scope for operators; out-of-scope records are hidden.
- **Auditability:** access log (sign-ins, failures, lockouts, account changes) and workflow audit trail (every tool call, proposal, approval and execution). Logs contain ids and codes — never passwords or tokens.
- **Secrets:** configuration through environment variables; `.env` and local credential notes are excluded from version control.

## 9. Responsible AI

- **AI is optional and off by default** (`AI_REPORTS_ENABLED`, `AI_WORKFLOW_ENABLED`).
- **Data minimisation:** only aggregated figures, machine/defect codes and short reasons are sent; never personal notes, names, tokens or passwords.
- **Grounded output:** reports and answers must cite evidence from measured data; invalid or unsupported output is rejected.
- **Human in the loop:** the AI can only *propose* changes; a supervisor approves the exact action, and the proposer cannot approve their own proposal.
- **Prompt-injection resistant:** plant records are passed to the model as untrusted data; tools are a fixed allowlist with no SQL, files, web or machine control.
- **Transparency:** AI-generated content is labelled, and synthetic demo data is flagged wherever it appears.

## 10. Technology stack

| Component | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, Pydantic v2, Uvicorn |
| Database | PostgreSQL 16+, SQLAlchemy 2.0, Alembic, psycopg 3 |
| AI | Google Gemini (optional) |
| Frontend | React 19, Vite 7, plain JavaScript and CSS |
| Security | scrypt (Python standard library), opaque hashed session tokens, role-based access control |
| Quality | Pytest, Ruff, Vitest, Testing Library, one-command verification script |
| Infrastructure | Docker Compose (PostgreSQL, migration job, API) |

## 11. Getting started

### Quick start (Windows, local PostgreSQL)

```powershell
# 1. Configure
# Create a local .env file and set DATABASE_URL and VITE_API_BASE_URL.
# See "Configure the environment" below; add a Gemini key only if AI is wanted.

# 2. Backend
cd backend
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head
python -m app.cli.seed --apply                               # optional: synthetic demo data
python -m app.cli.create_admin admin --name "Plant Admin"     # first admin account
uvicorn app.main:app --reload

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173 — sign in as the admin

# 4. Verify (project root)
powershell -ExecutionPolicy Bypass -File .\verify_all.ps1
```

After signing in as the admin, create accounts for supervisors, operators and
managers under **Users & access** and assign machines to operators.

### Detailed setup

#### Prerequisites

- **Python 3.11 – 3.13**
- **Node.js ≥ 20.19** (Vite 7 requirement) and npm
- **PostgreSQL 16** — either via Docker Compose (recommended) or a local install
- **Docker + Docker Compose v2** (optional but recommended)
- Git

---

#### 1. Configure the environment

Create a local `.env` file and add the settings below. Environment files are
intentionally not included in this repository. Set the values for your setup;
at minimum:

| Variable | Purpose |
|---|---|
| `POSTGRES_PASSWORD` | Password for the Compose PostgreSQL container. Use URL-safe characters. |
| `DATABASE_URL` | Connection URL used by the API and Alembic when run on the host. Must use the same password. |
| `CORS_ALLOWED_ORIGINS` | Browser origins allowed to call the API (default `http://localhost:5173`). |
| `VITE_API_BASE_URL` | API root used by the frontend (default `http://localhost:8000/api/v1`). |

Full list with descriptions: [Configuration reference](#13-configuration-reference).

The single root `.env` serves the backend, Compose and the frontend. Vite only
exposes `VITE_*` variables to browser code, so backend secrets are never bundled.

---

#### 2. Start PostgreSQL

**Option A — Docker Compose (recommended):**

```bash
docker compose up -d db
docker compose ps          # wait until db shows "healthy"
```

**Option B — existing local PostgreSQL** (e.g. Windows PostgreSQL 18):

Follow **[docs/local-database-setup.md](docs/local-database-setup.md)**. It covers
the `foundryos_app` role, keeping the password out of the repository (libpq
password file), read-only connection checks (`python scripts/check_db.py`) and
the `public` schema privilege that PostgreSQL 15+ requires for migrations.

---

#### 3. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

alembic upgrade head                 # apply migrations (required for readiness)

# Optional: load clearly labelled SYNTHETIC demo data (refused when ENVIRONMENT=production)
python -m app.cli.seed --apply

# Create the first admin (asks for the password; there are no default accounts)
python -m app.cli.create_admin admin --name "Plant Admin"

uvicorn app.main:app --reload --port 8000
```

- Liveness: <http://localhost:8000/api/v1/health/live>
- Readiness: <http://localhost:8000/api/v1/health/ready>
- API docs: <http://localhost:8000/docs> (when `ENABLE_API_DOCS=true`)

```bash
curl -i http://localhost:8000/api/v1/health/ready
# 200 {"status":"ready","checks":[{"name":"database","status":"pass",...},{"name":"migrations","status":"pass",...}]}
# 503 {"status":"not_ready",...} if the DB is down or migrations are not applied
```

#### Dependency locking

`requirements*.txt` use constrained ranges. After the first successful install,
freeze exact versions for reproducible builds and commit the lock:

```bash
pip freeze > requirements.lock
```

---

#### 4. Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

Commit the generated `package-lock.json`. Open <http://localhost:5173> and sign
in with the admin account you created in step 3.

Production build: `npm run build` (output in `frontend/dist/`), preview with `npm run preview`.

---

#### 5. Run the API in Docker (optional)

```bash
docker compose up -d --build
```

This starts `db`, runs the one-shot `migrate` job (`alembic upgrade head`),
then starts `backend` on `127.0.0.1:8000`. The frontend still runs on the host
with `npm run dev` (see architecture decision D5).

```bash
docker compose logs -f backend
docker compose down           # stop (data kept in the pgdata volume)
docker compose down -v        # stop AND delete database data
```

---

## 12. Testing and quality

One command checks everything on Windows (key files, lint, backend tests,
migration state, settings, accounts, frontend tests and production build):

```powershell
powershell -ExecutionPolicy Bypass -File .\verify_all.ps1
```


### Backend tests

```bash
cd backend
source .venv/bin/activate
pytest                      # unit tests — no running database required
```

Integration tests run against a real PostgreSQL database and are skipped unless
`TEST_DATABASE_URL` is set. **Use a dedicated, disposable database** — the tests
run `alembic upgrade head` against it.

```bash
TEST_DATABASE_URL=postgresql+psycopg://foundryos:your-password@localhost:5432/foundryos_test \
  pytest -m integration -v
```

Lint: `ruff check .`

### Frontend tests

```bash
cd frontend
npm test                    # Vitest, jsdom — fetch is stubbed, no backend needed
npm run build               # verifies the production bundle builds
```

---

## 13. Configuration reference

| Variable | Default | Description |
|---|---|---|
| `ENVIRONMENT` | `development` | `development`, `test` or `production`. Production enforces https-only, non-wildcard CORS. |
| `LOG_LEVEL` | `INFO` | Root log level. |
| `LOG_FORMAT` | `json` | `json` (one object per line) or `console`. |
| `ENABLE_API_DOCS` | `true` | Serve `/docs` and the OpenAPI schema. |
| `DATABASE_URL` | — (required) | `postgresql+psycopg://user:pass@host:5432/db`. `postgresql://` is accepted and normalised. |
| `DB_POOL_SIZE` | `5` | SQLAlchemy pool size. |
| `DB_MAX_OVERFLOW` | `10` | Extra connections beyond the pool. |
| `DB_POOL_TIMEOUT_SECONDS` | `30` | Wait time for a pooled connection. |
| `DB_CONNECT_TIMEOUT_SECONDS` | `5` | TCP connect timeout to PostgreSQL. |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Comma-separated origins. |
| `TEST_DATABASE_URL` | — | Enables integration tests. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | — | Compose PostgreSQL container. |
| `POSTGRES_PORT` / `BACKEND_PORT` | `5432` / `8000` | Host ports for Compose (bound to 127.0.0.1). |
| `VITE_API_BASE_URL` | — | Frontend → API root URL. |
| `AUTH_SESSION_TTL_MINUTES` | `480` | A session ends this long after sign-in (one shift). |
| `AUTH_IDLE_TIMEOUT_MINUTES` | `30` | …or after this much inactivity. |
| `AUTH_MAX_FAILED_LOGINS` / `AUTH_LOCKOUT_MINUTES` | `5` / `15` | Account lockout after wrong passwords. |
| `AUTH_RATE_LIMIT_ATTEMPTS` / `AUTH_RATE_LIMIT_WINDOW_SECONDS` | `10` / `300` | Sign-in attempts per client and per username. |
| `AI_REPORTS_ENABLED` / `AI_WORKFLOW_ENABLED` | `false` | Turn on AI shift reports / the workflow assistant. |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | — / `gemini-flash-latest` | AI provider settings (keep the key only in your local `.env`). |
| `WORKFLOW_ACCESS_TOKENS` | — | Deprecated Module 4 tokens; leave empty once everyone has an account. |

---

### Troubleshooting

| Symptom | Cause & fix |
|---|---|
| `permission denied for schema public` during `alembic upgrade head` | PostgreSQL 15+ does not grant `CREATE` on schema `public` by default. See [local-database-setup.md, Step 5](docs/local-database-setup.md#step-5--if-public-create-is-false-postgresql-15-behaviour). |
| `fe_sendauth: no password supplied` | URL has no password and no libpq password file entry matches. See [local-database-setup.md, Step 2](docs/local-database-setup.md#step-2--supply-the-password-choose-one-option). |
| API fails at startup with `database_url Field required` | `DATABASE_URL` not set. Create a local `.env` and set `DATABASE_URL` (the backend reads `.env` in `backend/` or the repo root). |
| `DATABASE_URL must be a PostgreSQL URL` | Use `postgresql+psycopg://…` (or `postgresql://…`). |
| `/health/ready` → 503, database `fail` | PostgreSQL not running or wrong credentials. `docker compose ps`; check `DATABASE_URL` host/port/password. Inside Compose the host is `db`; on the host it is `localhost`. |
| `/health/ready` → 503, migrations `fail` | Run `alembic upgrade head` from `backend/`. |
| `password authentication failed` after changing `POSTGRES_PASSWORD` | The volume keeps the original password. Either change it in PostgreSQL (`ALTER ROLE`) or reset with `docker compose down -v` (**deletes data**). |
| Frontend shows "Offline" | Backend not running, wrong `VITE_API_BASE_URL`, or the origin is not in `CORS_ALLOWED_ORIGINS`. Restart `npm run dev` after editing `.env`. |
| Frontend shows "Not configured" | `VITE_API_BASE_URL` missing/invalid in the root `.env`. |
| `Port 5173 is in use` | Another Vite server is running; stop it (strictPort is on to keep CORS predictable). |
| Startup refuses CORS settings in production | Production requires explicit `https://` origins; `*` is rejected. |
| `npm install` / `pip install` fail behind a corporate proxy | Configure `HTTPS_PROXY` and the proxy CA (`PIP_CERT`, `npm config set cafile …`). |

Every API error response contains a `request_id`, also returned in the
`X-Request-ID` header — search the logs for it.

---

## 14. Project structure

```
foundryos-ai/
├── backend/
│   ├── app/
│   │   ├── main.py            # application factory and entry point
│   │   ├── core/              # configuration, passwords, permissions, errors, logging
│   │   ├── db/                # SQLAlchemy base, engine/session, model registry
│   │   ├── models/            # manufacturing, reports, workflow and account tables
│   │   ├── api/               # versioned routers, authentication, data-scope checks
│   │   ├── schemas/           # request/response models
│   │   ├── services/          # analytics, shift reports, workflow agent, accounts
│   │   └── cli/               # seed, create_admin
│   ├── alembic/versions/      # 0001 baseline … 0005 accounts and roles
│   └── tests/                 # unit tests + opt-in PostgreSQL integration tests
├── frontend/
│   ├── public/demo/           # product walkthrough video (sign-in page)
│   └── src/
│       ├── api/               # session-aware HTTP client and endpoint functions
│       ├── auth/              # sign-in state and session storage
│       ├── components/        # shared UI, dashboard, reports, assistant
│       ├── pages/             # sign-in, my machines, dashboard, reports, assistant, admin, account
│       ├── lib/               # KPI maths, formatting, access rules, PDF export
│       └── styles/            # screen and print styles
├── docs/                      # architecture and per-module documentation
├── verify_all.ps1             # one-command verification (Windows)
├── docker-compose.yml
```

## 15. Documentation

| Topic | Document |
|---|---|
| Architecture and data flow | [`docs/architecture.md`](docs/architecture.md) |
| Local PostgreSQL setup (Windows) | [`docs/local-database-setup.md`](docs/local-database-setup.md) |
| Manufacturing data model and API | [`docs/module-1-manufacturing-data.md`](docs/module-1-manufacturing-data.md) |
| Dashboard and KPI definitions | [`docs/module-2-dashboard.md`](docs/module-2-dashboard.md) |
| AI shift reports and data sent to the AI | [`docs/module-3-shift-reports.md`](docs/module-3-shift-reports.md) |
| Workflow assistant and human approval | [`docs/module-4-workflow-agent.md`](docs/module-4-workflow-agent.md) |
| Accounts, roles, sessions, first admin | [`docs/module-5-auth-rbac.md`](docs/module-5-auth-rbac.md) |
| Deploying on AWS (one EC2 server, HTTPS, demo accounts) | [`docs/deployment-aws.md`](docs/deployment-aws.md) |
| Creating the AWS server with Terraform | [`docs/deployment-terraform.md`](docs/deployment-terraform.md) |
| Web client on Cloudflare Pages, API on AWS | [`docs/deployment-cloudflare-pages.md`](docs/deployment-cloudflare-pages.md) |
| Roadmap and verification log | [`docs/module-checklist.md`](docs/module-checklist.md) |

## 16. Limitations and roadmap

**Current limitations**
- Runs locally; not yet deployed or validated in a production plant. Demo figures are synthetic.
- Machine events are entered by people; there is no PLC/IoT, MES or ERP integration yet.
- No email delivery, single sign-on or multi-factor authentication.
- Supervisors see the whole plant; team/line scopes are not modelled yet.
- AI answers are checked for cited evidence, not figure by figure, and must be reviewed by a person.

**Roadmap**
- Maintenance workflow: assignment, status tracking, SLAs and notifications
- CSV/Excel import of historical production data
- Machine connectivity (PLC/IoT) for automatic downtime capture
- Server-side scheduled PDF/Excel reports
- Cloud deployment with CI/CD, backups and monitoring
- SSO and multi-factor authentication

---

## Author

**Kuldip Mahale** — [GitHub](https://github.com/Kuldip8975) · [LinkedIn](https://www.linkedin.com/in/kuldip-mahale-ab3a45240)
