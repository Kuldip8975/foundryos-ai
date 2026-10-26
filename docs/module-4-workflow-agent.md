# Module 4 — AI Workflow Agent & Human Approval

The assistant answers natural-language questions about machines, downtime, production, quality and maintenance. It uses a fixed set of typed, read-only tools. It can also **prepare** a maintenance request, but a supervisor must approve that request before anything is written.

**What decides what:**
- **The language model** plans: it picks tools, supplies arguments and writes the answer.
- **The backend** runs the tools, checks permissions, enforces limits, validates the output and executes approved actions.

## Roles and access

There is no user database yet. People are configured with access tokens in the server's `.env` file:

```
WORKFLOW_ACCESS_TOKENS=alice:supervisor:<sha256>,olga:operator:<sha256>,vic:viewer:<sha256>
```

Create an entry with the command below. It prints a token once (give it to the person) and the entry for `.env`; only the SHA-256 hash is stored.

```
cd backend
python -m app.cli.workflow_token alice supervisor
```

The browser sends the token as `Authorization: Bearer …`. It is kept only in the tab's `sessionStorage`.

| Role | Ask (read-only tools) | Prepare maintenance request | Approve / reject | See everyone's sessions |
|---|---|---|---|---|
| viewer | ✓ | — | — | — (own only) |
| operator | ✓ | ✓ | withdraw own | — (own only) |
| supervisor | ✓ | ✓ | ✓ | ✓ |

**Separation of duties:** `WORKFLOW_REQUIRE_DISTINCT_APPROVER=true` (the default) means the person who prepared an action cannot approve it.

**Visibility:** sessions and proposals that belong to someone else return 404, so their ids are not disclosed.

## Tools (the complete allowlist — `app/services/workflow/tools.py`)

| Tool | Kind | Limits |
|---|---|---|
| `get_machine_status` | read | ≤ 50 machines. "running" means no ongoing downtime is recorded (not live telemetry). |
| `query_downtime` | read | Range ≤ 31 days. Uses the Module 2 overlap rules. ≤ 20 recent events; reasons truncated to 160 chars. |
| `get_production_quality_metrics` | read | Range ≤ 92 days. Uses the Module 2/3 ratio definitions; a zero denominator gives `null`. |
| `list_maintenance_requests` | read | ≤ 20 rows. Descriptions truncated to 200 chars. |
| `prepare_maintenance_request` | proposal | Writes nothing. The machine must exist and be active. One per question. |

**How every call is checked:** each call is checked in this order — tool allowlist, role permission, argument size, per-question limits, then the strict Pydantic model (unknown fields refused, strict integers, date ranges).

**Refused calls:** a refused call is recorded as a step with a reason and is fed back to the model. It is never executed.

**No other capabilities:** there is no SQL, shell, file, URL or machine-control capability. Each tool query has a 5 s statement timeout on PostgreSQL.

## Agent loop (`app/services/workflow/agent.py`)

1. **Start:** the backend stores the session (`running`) and an audit event.
2. **Each round:** the model gets three things:
   - the question;
   - only the tools this person's role allows;
   - earlier results labelled `E1, E2, …`, wrapped as **untrusted data**. The prompt says never to follow instructions found inside records.
3. **The model replies** with `tool_calls` (1–4) or `final`. The reply is validated strictly.
4. **Final answer checks:** every finding must cite evidence ids of successful tool calls. Invented ids are rejected (`ai_invalid_output`).
5. **Limits** (configurable):

   | Setting | Default | Effect |
   |---|---|---|
   | `WORKFLOW_MAX_TOOL_CALLS` | 8 | Further calls are refused with `tool_call_limit`. |
   | `WORKFLOW_MAX_ROUNDS` | 4 | The last round must be final, otherwise `agent_step_limit`. |
   | `WORKFLOW_TIMEOUT_SECONDS` | 120 | Whole-run budget. Each model call gets only what is left of it, otherwise `workflow_timeout`. |

6. **Failures:** provider failures reuse the Module 3 codes (`ai_rate_limited`, `ai_timeout`, `ai_provider_error`, `ai_network_error`, …). The failed session is stored, and the error carries `details: [{"session_id": …}]`.

## Approval (`app/services/workflow/approvals.py`)

A proposal stores the action, its exact arguments and a preview. It also stores an `arguments_hash`: a SHA-256 over the proposal id, session id, action, arguments, target machine id and expiry time.

Approving requires `{arguments_hash, idempotency_key, note?}`. Before anything is written:

| Check | Failure |
|---|---|
| Role may decide; not self-approval | 403 `forbidden` / `self_approval_forbidden` |
| Same idempotency key from the same person for the same decision | 200, returns the recorded outcome (no second execution) |
| Key used for a different proposal or decision | 409 `idempotency_key_reused` |
| Not past `expires_at` (`WORKFLOW_PROPOSAL_TTL_MINUTES`, default 15) | 409 `proposal_expired` |
| Still `pending_approval` (replay protection) | 409 `proposal_not_pending` |
| Submitted hash equals the stored hash | 409 `approval_mismatch` |
| Stored hash equals a recomputed hash (tamper check) | 422 `integrity_check_failed` |
| Arguments re-validated; machine still exists, is the same machine and is active | 422 `revalidation_failed` |

**One transaction:** execution writes, in a single transaction:
- the decision row (unique per proposal);
- the maintenance request (`external_ref = wf-proposal-<id>`, unique);
- a conditional status update (`WHERE status = 'pending_approval'`);
- the audit events.

**Confirmation:** success is returned only after the commit, once the new request has been read back from the database.

**Rejecting and withdrawing:** supervisors may reject; the author may withdraw their own proposal. Pending proposals past their expiry are marked `expired` when history is read.

## API (`/api/v1/workflows`, all require a bearer token)

| Method & path | Purpose |
|---|---|
| `GET /workflows/me` | Name, role and permissions of the token |
| `POST /workflows` `{question}` | Run the agent (201). The session holds the answer, steps, proposal and audit events. |
| `GET /workflows?status&proposal_status&limit&offset` | History (own sessions; supervisors see all) |
| `GET /workflows/{id}` | One session with its full audit trail |
| `POST /workflows/proposals/{id}/approve` | Approve and execute exactly the shown action |
| `POST /workflows/proposals/{id}/reject` `{idempotency_key, note?}` | Reject, or withdraw (author) |

Other errors: `401 unauthorized` (with `WWW-Authenticate: Bearer`), `503 workflow_auth_not_configured`, `503 ai_not_configured`.

## Persistence (migration `0004_workflow_agent` — write-only, not applied)

The migration adds these tables:
- `workflow_sessions`;
- `workflow_steps`;
- `action_proposals`;
- `action_approvals`;
- `workflow_audit_events`.

Audit events are append-only and contain ids, codes and counts. They never contain tokens, token hashes, prompts or free text. No existing table or row is changed.

**Apply it yourself:** `alembic upgrade head`.

## What is sent to Gemini

The model receives:
- the question;
- tool descriptions and argument schemas;
- tool results: machine codes and names, aggregated figures, short downtime reasons, short maintenance issue descriptions, and maintenance request ids.

The model never receives:
- production or inspection notes;
- resolution notes;
- person names or tokens.

## Frontend (`#/assistant`)

- **Sign in:** a token box with local validation and server check, then a sign-out control.
- **Ask:** a question box with local validation (3–1000 characters), example prompts, and a progress state while running.
- **Answer:**
  - labelled as AI-generated;
  - synthetic-data notice;
  - findings with evidence chips that link to the tool calls;
  - limitations.
- **Proposal panel:**
  - full preview, expiry and approval code;
  - an explicit "I have reviewed" step before **Approve**;
  - an optional note;
  - **Reject**, or **Withdraw** for the author;
  - progress while executing;
  - the confirmed result (request id and reference).
  - A retry after a network error reuses the same idempotency key.
- **Tool calls:** every call, including refused ones, with its arguments and result.
- **Audit trail and history:** paginated, with a filter on proposal status.
- **Errors:** sign-in, validation, network and provider errors each have their own message. A failed run links to its saved attempt.

## Verify locally

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
ruff check .
pytest -q
alembic upgrade head          # applies 0004_workflow_agent (your decision; dev database)
cd ..\frontend
npm test
npm run build
```

To try it:

1. Create tokens with `python -m app.cli.workflow_token …`.
2. In `.env`, set `AI_WORKFLOW_ENABLED=true`, `WORKFLOW_ACCESS_TOKENS=…` and the Gemini key.
3. Restart uvicorn and open `#/assistant`.

## Known limitations

- **Authentication:** token-based only. There is no user database, password login, token expiry or rotation workflow; revoke a token by removing its entry and restarting the server.
- **Module 1–3 endpoints:** these are still unauthenticated (unchanged by this module). Anyone who can reach the API can still write maintenance requests directly. The approval flow protects only changes made **through the assistant**.
- **Free text in AI answers:** it is not checked number-by-number against the tool results; only the cited evidence ids are checked. Answers must be reviewed by a person.
- **Request handling:**
  - the agent runs inside the request (no background queue), so one long run holds a worker thread;
  - expiry is applied lazily when history is read.
- **Not production-ready:** there has been no deployment, load or security review.