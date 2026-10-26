# Module 5 — Private accounts, role-based access and role dashboards

FoundryOS is now a private system:
- every page and every API endpoint except health checks and sign-in needs a signed-in account;
- there is no sign-up;
- only an admin creates accounts.

Each role sees its own start page and only the pages and data it is allowed to.

## Roles and permissions

The permission table is fixed in backend code (`app/core/permissions.py`) and checked on every request.

- **Role comes from the server.** A role sent by the browser — in the body, a header or the query string — is never used. The server reads the session, then the user's current role, from the database.
- **The interface only follows the server.** It hides what a role cannot use, but the server is the protection.

| Permission | Operator | Supervisor | Production manager | Admin |
|---|:-:|:-:|:-:|:-:|
| Machines/products list (`machines:read`) | own machines | ✓ | ✓ | ✓ (to assign machines) |
| Create/update machines, products, defects (`master_data:manage`) | | | ✓ | |
| Read production, quality, downtime, maintenance | own machines | ✓ | ✓ | |
| Record production, quality, downtime (`*:record`) | own machines | ✓ | | |
| Create/update maintenance requests directly (`maintenance:manage`) | | ✓ | | |
| Plant dashboard and shift analysis (`analytics:read`) | | ✓ | ✓ | |
| Read and generate AI shift reports | | ✓ | ✓ | |
| Workflow assistant (`assistant:use`) | operator role | supervisor role | viewer role | |
| Approve or reject assistant actions (`actions:approve`) | | ✓ | | |
| Manage accounts (`users:manage`), read access log (`audit:read`) | | | | ✓ |

**Start pages:**
- Operator → **My machines**: machine status, report downtime, record shift output, and their own lists.
- Supervisor and production manager → **Dashboard**.
- Admin → **Users & access**.

### Data scope

Operators work only with the machines an admin assigns to them.

**Lists are limited.** Production records, quality inspections, downtime, maintenance and the machine list contain only assigned machines.

**Other machines are hidden or refused:**
- Opening a record from another machine answers **404**, exactly like a missing record.
- Recording data for another machine answers **403 `machine_not_assigned`**.
- A production record without a machine answers **422 `machine_required`**.

**Assistant tools are limited too.** For an operator:
- every tool needs one of their machine codes;
- "status of all machines" lists only theirs;
- refused calls are recorded as steps (`machine_not_assigned`, `machine_required`).

**Supervisors and production managers see the whole plant.** The plant has no team or line structure yet.

**Changes apply on the next request.** Changing someone's role or machines needs no new sign-in.

### Human approval (unchanged from Module 4)

- Operators **prepare** maintenance requests through the assistant.
- Only a **supervisor** can approve or reject them, and never their own; the distinct-approver rule still applies.
- Production managers and admins cannot approve.
- Direct `POST /maintenance-requests` is now limited to supervisors, so operators cannot bypass approval.

## Sessions and passwords

**Passwords**
- Stored as salted **scrypt** hashes using Python's standard library — no new dependency.
- Cost N=2^15, r=8, p=3 (OWASP); older hashes are upgraded at the next sign-in.
- Rules: 12–128 characters, not too repetitive, not a common password, must not contain the username.

**Sessions**
- **Token:** a 256-bit random token, returned once at sign-in. The browser sends it as `Authorization: Bearer …`.
- **Stored only as a hash:** the database holds the token's SHA-256, never the token.
- **Kept per tab:** the browser keeps it in `sessionStorage` for that tab only.
- **No cookies:** so cross-site request forgery does not apply.

**When sessions end**

| Event | Result |
|---|---|
| 8 hours after sign-in (`AUTH_SESSION_TTL_MINUTES`) | Session expires |
| 30 minutes without activity (`AUTH_IDLE_TIMEOUT_MINUTES`) | Session expires |
| Sign out | That session ends |
| Account deactivated | All its sessions end immediately |
| Admin password reset | All its sessions end immediately |
| Own password change | All its *other* sessions end |

After a session ends, the next request answers **401** and the app returns to the sign-in page with an explanation.

**Sign-in protection**
- **Same answer for every failure:** an unknown user, wrong password, locked account or deactivated account all get the same "Sign-in failed" message.
- **Same timing:** unknown users are checked against a dummy hash, so failures take the same time.
- **Account lockout:** after 5 wrong passwords the account is locked for 15 minutes. This is stored in the database, so it applies across server processes.
- **Rate limit:** 10 attempts per 5 minutes per computer and per username, then **429**. This limit is kept in memory, per server process.

**Temporary passwords**
- An admin-created account, or an admin password reset, gets a server-generated **one-time password**.
- It is shown once, to the admin.
- The person must choose their own password before anything else opens; until then the API answers **403 `password_change_required`**.

**Access log** (`auth_audit_events`) records:
- sign-ins and failures;
- lockouts and session expiry;
- sign-outs;
- password changes and resets;
- account changes.

It holds ids, roles, codes and counts. It never holds passwords, tokens, token hashes, or the text typed into a failed sign-in.

## Database (migration `0005_auth_rbac`)

The migration adds four tables:
- `users`
- `user_machine_assignments`
- `auth_sessions`
- `auth_audit_events`

No existing table or row is changed. The migration creates **no** account and contains no credentials.

## Safe procedure: apply the migration and create the first admin

Run these steps on your own computer, in this order.

1. **Back up the database first.** This is optional but recommended. `pg_dump` lives in your PostgreSQL `bin` folder:
   ```powershell
   pg_dump -h 127.0.0.1 -U foundryos_app -d foundryos -F c -f foundryos_before_module5.dump
   ```
2. **Stop uvicorn.** Then apply the migration:
   ```powershell
   cd E:\foundryos-ai-module0\backend
   .\.venv\Scripts\Activate.ps1
   alembic current          # expect 0004_workflow_agent (head)
   alembic upgrade head     # applies 0005_auth_rbac
   alembic current          # expect 0005_auth_rbac (head)
   ```
3. **Create the first admin.** This works only while no active admin exists.
   ```powershell
   python -m app.cli.create_admin admin --name "Plant Admin"
   ```
   - It asks for the password twice. Nothing is shown on screen or saved in shell history.
   - Alternative: add `--generate-password` to print a one-time password instead. It must be changed at the first sign-in.
4. **Start the apps.** Start uvicorn and the frontend (`npm run dev`), then sign in as that admin.
5. **Create the other accounts** in **Users & access** → **New account**. Assign machines to operators. Give each person their one-time password privately.
6. **Retire the old tokens.** Once everyone has an account, empty `WORKFLOW_ACCESS_TOKENS` in `.env` and restart uvicorn. The old Module 4 tokens still work until then, but only on the `/workflows` API.

**Undo:** `alembic downgrade 0004_workflow_agent` removes only the four new tables.

## API

| Method & path | Who | Purpose |
|---|---|---|
| `POST /auth/login` `{username, password}` | anyone | Sign in with a username or work email; returns `access_token`, `expires_at` and `user` |
| `GET /auth/me` | signed in | Role, permissions, start page, assigned machines, session expiry |
| `POST /auth/logout` | signed in | End this session (204) |
| `POST /auth/password` `{current_password, new_password}` | signed in | Change own password (required after a temporary one) |
| `GET /admin/users` | admin | List accounts (filters: `role`, `is_active`, `q`) |
| `POST /admin/users` | admin | Create an account; returns a one-time password |
| `PATCH /admin/users/{id}` | admin | Name, email, role, machines |
| `POST /admin/users/{id}/status` `{is_active}` | admin | Deactivate (ends all sessions) or reactivate |
| `POST /admin/users/{id}/reset-password` | admin | Issue a one-time password and end all sessions |
| `GET /admin/audit-events` | admin | Access log (filters: `event_type`, `user_id`, `success`) |

**Admin safeguards:**
- Admins cannot deactivate, demote or reset themselves (`self_change_forbidden`).
- The last active admin can never be demoted or deactivated (`last_admin`).

## Frontend

- **Sign-in page**
  - Two-column layout: FoundryOS overview on the left, sign-in form on the right.
  - Local validation, loading state, the server's generic error, and notices for "session expired" and "signed out".
  - No sign-up link.
- **Protected routes**
  - Nothing loads until the session is confirmed with `GET /auth/me`.
  - Pages outside the role show "This page is not part of your role" with a link to the start page.
  - After sign-in the person goes to their start page, unless they followed a link to a page their role allows.
- **Required password change**
  - A full-page step before anything else opens.
- **My account**
  - Profile, machines, when the session ends, and a change-password form.
- **Users & access** (admin)
  - Accounts table with search and filters.
  - Create and edit accounts, with the machine picker shown only for operators.
  - Reset password: asks inline first, then shows the one-time password with a Copy button.
  - Deactivate: asks inline first; reactivate.
  - Access log with event and outcome filters.
- **My machines** (operator)
  - Current downtime per machine.
  - "Report downtime" and "Record shift output" forms, with the server's rules checked locally first.
  - Lists of their downtime, output and maintenance requests.
- **Workflow assistant**
  - Uses the signed-in session; the token box is gone.
  - Shows the assistant role mapped from the account role.
- **Session handling**
  - Any **401** to a request that carried the session ends it and returns to sign-in.
  - The browser also ends the session at its absolute expiry time.

## Verification

### Performed in the build environment (15 Oct 2026)
- **Backend lint:** `ruff check .` — all checks passed.
- **Backend tests:** `pytest` — **483 passed, 2 skipped**.
  - 84 new tests in `test_auth_rbac.py` and `test_create_admin_cli.py`.
  - The 2 skipped tests need `TEST_DATABASE_URL`.
- **PostgreSQL 16 integration:** `pytest tests/test_db_integration.py` with `TEST_DATABASE_URL` — 2 passed. Migrations upgrade to head (0005) and readiness passes.
- **Model check on PostgreSQL 16:** the schema compared against the models with type comparison — **no differences**.
- **Upgrade keeps existing data:** synthetic data was loaded, then `downgrade 0004` and `upgrade 0005` were run.
  - Machines, production records, inspections, downtime and maintenance row counts were identical before and after.
- **Backend end-to-end over HTTP** (uvicorn + PostgreSQL 16, production password cost):
  - **Admin bootstrap:** `create_admin` worked; a second run was refused; the generated password was forced to change.
  - **Accounts:** the admin created a supervisor, an operator with one machine and a production manager.
  - **Role checks:** the operator saw only their machine; the role-permission checks gave 403 where expected; recording downtime on an unassigned machine gave 403.
  - **Ending access:** deactivation ended the session; logout revoked the token.
  - **No secrets leaked:** neither the access log nor the server log contained any password or token.
- **Real browser end-to-end:** Chromium via Playwright, with the frontend bundled by esbuild because Vite could not be installed.
  - Sign-in validation and failure message.
  - Admin landing page, account creation and one-time password display.
  - Access log and sign-out.
  - Forced password change.
  - Operator start page and recording downtime.
  - Forbidden page; supervisor dashboard; idle-expired session back to sign-in.
  - Deep link kept after sign-in; assistant using the session; account page.
  - Mobile layout with no horizontal scroll; no console errors.

### Not performed here — run on the developer machine
- **`npm test` (Vitest) and `npm run build` (Vite)** could not run: npm packages cannot be downloaded in the build environment.
  - New and updated tests: `App.auth.test.jsx`, `App.routing.test.jsx`, `App.test.jsx`, `AssistantPage.test.jsx`, `AdminPage.test.jsx`, `MyWorkPage.test.jsx`, `client.test.js`.
  - They were syntax-checked and their imports verified, but not run.
- **Real Gemini run with an account session** — the earlier Module 4 Gemini run used legacy tokens.
- **`verify_all.ps1` on Windows.**

## Known limitations

- **Rate limiter:** in memory, per server process. With several workers each keeps its own count; the database lockout still applies everywhere.
- **No email:** there is no email delivery, so an admin passes one-time passwords to people directly.
- **Supervisor scope:** supervisors and production managers see the whole plant; there is no team or line structure yet.
- **Client address:** the rate limit uses the address uvicorn sees. Behind a reverse proxy, configure the proxy's forwarded-for handling first.
- **Legacy tokens:** `WORKFLOW_ACCESS_TOKENS` (Module 4) still works on `/workflows` until you empty it.
- **Not production-ready:** no multi-factor authentication or SSO; no security review or load test has been done.