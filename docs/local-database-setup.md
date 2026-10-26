# Local database setup (Windows · PostgreSQL 18)

How to connect FoundryOS AI to a locally installed PostgreSQL server **without
committing or printing the database password**, and how to verify each
connection before running any migration.

Assumed state (already done by you):

| Item | Value |
|---|---|
| Server | PostgreSQL 18 on `127.0.0.1:5432` |
| Application database | `foundryos` |
| Integration-test database | `foundryos_test` (disposable) |
| Login role | `foundryos_app` (password set with `\password`) |
| Migrations | none applied yet |

All commands are PowerShell, run from the repository root unless stated otherwise.
If `psql` is not on your `PATH`, use its full path, typically
`& "C:\Program Files\PostgreSQL\18\bin\psql.exe"`.

---

## Step 1 — Create the root `.env`

Create a local `.env` file in the repository root. Environment files are
intentionally not included in this repository.

Add the following connection URLs, with **no password in them**:

```dotenv
DATABASE_URL=postgresql+psycopg://foundryos_app@127.0.0.1:5432/foundryos
TEST_DATABASE_URL=postgresql+psycopg://foundryos_app@127.0.0.1:5432/foundryos_test
```

- `postgresql+psycopg://` is the required SQLAlchemy driver prefix (psycopg 3).
- Use `127.0.0.1`, not `localhost`. On Windows, `localhost` may resolve to IPv6 `::1`, and the password-file entry below must match the host exactly.
- The `POSTGRES_*` variables in `.env` are only used by Docker Compose and can be left as they are.

Confirm Git ignores the file. Both commands are read-only:

```powershell
git check-ignore -v .env      # expected: .gitignore:2:.env	.env
git status --short            # .env must NOT appear in the list
```

Make sure there is **no** `backend\.env`. The backend reads `.env` from the
current directory and from `..\.env`. Always run backend commands from `backend\`,
so that the root `.env` is the one used.

---

## Step 2 — Supply the password (choose one option)

### Option A (recommended): PostgreSQL password file

libpq is used by both `psql` and the application's psycopg driver. When a URL has
no password, libpq reads it from `%APPDATA%\postgresql\pgpass.conf`. That file
lives outside the repository.

```powershell
New-Item -ItemType Directory -Force "$env:APPDATA\postgresql" | Out-Null
notepad "$env:APPDATA\postgresql\pgpass.conf"
```

Type these two lines in Notepad, replacing `YOUR_PASSWORD` yourself, and save:

```
127.0.0.1:5432:foundryos:foundryos_app:YOUR_PASSWORD
127.0.0.1:5432:foundryos_test:foundryos_app:YOUR_PASSWORD
```

- If the password contains `:` or `\`, escape each with a backslash (`\:` and `\\`).
- No URL-encoding is needed here.
- Optional hardening, so only your account can read the file:

  ```powershell
  icacls "$env:APPDATA\postgresql\pgpass.conf" /inheritance:r /grant:r "$($env:USERNAME):(R,W)"
  ```

### Option B: per-session environment variable

The password exists only in the current PowerShell window. PowerShell 7.1+:

```powershell
$env:PGPASSWORD = Read-Host -Prompt "foundryos_app password" -MaskInput
# ... run the checks ...
Remove-Item Env:PGPASSWORD
```

### Option C: password inside `.env`

Edit `.env` and insert the password into both URLs:
`postgresql+psycopg://foundryos_app:PASSWORD@127.0.0.1:5432/foundryos`.

- URL-encode special characters: `@`→`%40`, `:`→`%3A`, `/`→`%2F`, `%`→`%25`, `#`→`%23`, `?`→`%3F`.
- The file is git-ignored, but the password is then stored in plain text inside the project folder. Prefer Option A.

---

## Step 3 — Verify with `psql` (read-only)

`-w` tells psql never to prompt, so success proves the password source from
Step 2 works non-interactively, the way the application will use it. With
Option B, run these in the same window where `PGPASSWORD` is set.

```powershell
psql -h 127.0.0.1 -p 5432 -U foundryos_app -d foundryos -w -c "SELECT current_user, current_database(), version();"
psql -h 127.0.0.1 -p 5432 -U foundryos_app -d foundryos_test -w -c "SELECT current_user, current_database();"
```

Check the privileges that migrations will need:

```powershell
psql -h 127.0.0.1 -U foundryos_app -d foundryos -w -c "SELECT has_database_privilege(current_database(),'CONNECT') AS db_connect, has_schema_privilege('public','USAGE') AS schema_usage, has_schema_privilege('public','CREATE') AS schema_create;"
psql -h 127.0.0.1 -U foundryos_app -d foundryos_test -w -c "SELECT has_database_privilege(current_database(),'CONNECT') AS db_connect, has_schema_privilege('public','USAGE') AS schema_usage, has_schema_privilege('public','CREATE') AS schema_create;"
```

All three values must be `t` in both databases. If `schema_create` is `f`, see Step 5.

---

## Step 4 — Verify with the application's own driver and configuration

`scripts/check_db.py` reads `DATABASE_URL` / `TEST_DATABASE_URL` exactly as the
application does (environment first, then `.env`). For each target it:

- opens a **read-only** session (`default_transaction_read_only=on`) and runs only `SELECT` statements;
- reports the user, database, server version, privileges and migration state;
- never prints a password and never prompts for one.

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python scripts\check_db.py                 # DATABASE_URL      -> foundryos
python scripts\check_db.py --target test   # TEST_DATABASE_URL -> foundryos_test
```

Expected output on success (values will differ):

```
Target         : DATABASE_URL
URL            : postgresql+psycopg://foundryos_app@127.0.0.1:5432/foundryos
Password source: libpq password file (PGPASSFILE / pgpass.conf / ~/.pgpass)
Connected as   : foundryos_app -> database foundryos (PostgreSQL 18.x)
Read-only sess.: on
DB  CONNECT    : True
DB  CREATE     : True
public USAGE   : True
public CREATE  : True
Migrations     : not applied (no alembic_version)
OK    connection verified (read-only check; nothing was changed)
```

| Exit code | Meaning |
|---|---|
| `0` | Connected, and the role can create tables in `public` |
| `1` | Connection or authentication failed (message shown, never the password) |
| `2` | Configuration error: URL missing or malformed; for `--target test`, the database name must end in `_test` and differ from `DATABASE_URL` |
| `3` | Connected, but the role cannot create tables in `public`; `alembic upgrade head` would fail (see Step 5) |

Check the exit code in PowerShell with `$LASTEXITCODE`.

---

## Step 5 — If `public CREATE` is false (PostgreSQL 15+ behaviour)

Since PostgreSQL 15, ordinary roles no longer have `CREATE` on the `public`
schema by default. `CONNECT` and `CREATE` on the **database** do not let a role
create tables in `public`. That requires `CREATE` on the **schema**.

Run this yourself as a superuser (for example `postgres`). It changes
privileges only; no data is created or removed.

```powershell
psql -h 127.0.0.1 -U postgres -d foundryos      -c "GRANT USAGE, CREATE ON SCHEMA public TO foundryos_app;"
psql -h 127.0.0.1 -U postgres -d foundryos_test -c "GRANT USAGE, CREATE ON SCHEMA public TO foundryos_app;"
```

Then repeat Step 4. Both targets should exit `0`.

---

## Step 6 — Later, as a separate, deliberate step: migrations and integration tests

These commands **change the databases**. Run them only when you intend to.

```powershell
cd backend
alembic upgrade head        # creates table alembic_version (revision 0001_baseline) in foundryos
```

Integration tests read `TEST_DATABASE_URL` from the **process environment only**,
never from `.env`, so a plain `pytest` cannot touch any database. To run them,
set the variable for one session:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://foundryos_app@127.0.0.1:5432/foundryos_test"
pytest -m integration -v    # runs `alembic upgrade head` against foundryos_test
Remove-Item Env:TEST_DATABASE_URL
```

The integration tests refuse to run (fail, without connecting) unless the URL
uses `postgresql+psycopg://` and the database name ends in `_test`.

---

## Troubleshooting

| Message | Cause and fix |
|---|---|
| `fe_sendauth: no password supplied` | No usable password source. Check that `pgpass.conf` is in `%APPDATA%\postgresql\` (not `%LOCALAPPDATA%`), that the host is exactly `127.0.0.1`, and that port, database and user match. Notepad may save it as `pgpass.conf.txt`: check with `Get-ChildItem "$env:APPDATA\postgresql"`. |
| `password authentication failed for user "foundryos_app"` | The password source is found but the password is wrong. Re-check the entry; escape `:` and `\` in `pgpass.conf`, or URL-encode in `.env`. |
| `connection refused` / timeout | The server is not running or not listening on `127.0.0.1:5432`. Check the service (`Get-Service postgresql*`) and `listen_addresses` in `postgresql.conf`. |
| `no pg_hba.conf entry for host` | `pg_hba.conf` has no rule for `127.0.0.1/32` with `scram-sha-256` for this role and database. |
| `permission denied for schema public` (during migrations) | See Step 5. |
| `DATABASE_URL must start with postgresql+psycopg://` | Fix the prefix in `.env`. |
| Wrong database used | A `backend\.env`, or a `PGPASSFILE`/`DATABASE_URL` environment variable, overrides the root `.env`. Check with `Get-ChildItem Env:DATABASE_URL, Env:PGPASSFILE -ErrorAction SilentlyContinue`. |
