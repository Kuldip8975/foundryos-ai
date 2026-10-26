import { useId, useMemo, useState } from 'react';
import {
  ROLES,
  createUser,
  fetchAuditEvents,
  fetchUsers,
  resetUserPassword,
  roleLabel,
  setUserActive,
  updateUser,
  validateChosenPassword,
  validateNewUser,
} from '../api/admin.js';
import { fetchMachines } from '../api/manufacturing.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { InlineSelect, PagedListCard } from '../components/dashboard/PagedListCard.jsx';
import { PrintButton, PrintHeader } from '../components/PrintButton.jsx';
import { StatusBadge } from '../components/StatusBadge.jsx';
import { Card } from '../components/ui/Card.jsx';
import { DataTable } from '../components/ui/DataTable.jsx';
import { Pagination } from '../components/ui/Pagination.jsx';
import { EmptyMessage, ErrorCallout, LoadingState } from '../components/ui/StateViews.jsx';
import { useApiResource } from '../hooks/useApiResource.js';
import { formatDateTime, humanize } from '../lib/format.js';
import { pdfFileTitle } from '../lib/print.js';

const PAGE_SIZE = 20;

export function accountStatus(user, now = new Date()) {
  if (!user.is_active) return 'account_inactive';
  if (user.locked_until && new Date(user.locked_until) > now) return 'account_locked';
  if (user.must_change_password) return 'account_password_pending';
  return 'account_active';
}

const ROLE_FILTER = [{ value: '', label: 'All roles' }, ...ROLES.map((r) => ({ value: r.value, label: r.label }))];
const STATUS_FILTER = [
  { value: '', label: 'All' },
  { value: 'true', label: 'Active' },
  { value: 'false', label: 'Deactivated' },
];

/** Shown once after an account is created or a password is reset. */
function OneTimePassword({ result, onDismiss }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(result.temporary_password);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="callout callout--info one-time" role="status" aria-label="One-time password">
      <p>
        <strong>One-time password for {result.user.username}.</strong> Give it to {result.user.display_name} in
        person. It is shown only now; they must choose their own password when they first sign in.
      </p>
      <div className="one-time__row">
        <code className="one-time__value">{result.temporary_password}</code>
        <button type="button" className="button--small" onClick={copy}>
          {copied ? 'Copied' : 'Copy'}
        </button>
        <button type="button" className="button--ghost button--small" onClick={onDismiss}>
          Done
        </button>
      </div>
    </div>
  );
}

function MachinePicker({ machines, selected, onChange, idPrefix }) {
  if (!machines) return <LoadingState label="Loading machines…" />;
  if (machines.length === 0) return <EmptyMessage>No machines exist yet.</EmptyMessage>;
  const toggle = (machineId) =>
    onChange(selected.includes(machineId) ? selected.filter((m) => m !== machineId) : [...selected, machineId]);
  return (
    <fieldset className="machine-picker">
      <legend>Assigned machines</legend>
      {machines.map((m) => (
        <label key={m.id} htmlFor={`${idPrefix}-${m.id}`} className="machine-picker__item">
          <input
            id={`${idPrefix}-${m.id}`}
            type="checkbox"
            checked={selected.includes(m.id)}
            onChange={() => toggle(m.id)}
          />
          {m.code} — {m.name}
          {m.is_active ? '' : ' (inactive)'}
        </label>
      ))}
    </fieldset>
  );
}

/**
 * Optional admin-chosen password. Empty = the server generates a one-time
 * password, which the person must always change at first sign-in.
 */
function PasswordFields({ idPrefix, values, errors, onChange, emptyHint }) {
  return (
    <fieldset className="password-choice">
      <legend>Password</legend>
      <div className="user-form__fields">
        <div className="field">
          <label htmlFor={`${idPrefix}-pw`}>Password (optional)</label>
          <input
            id={`${idPrefix}-pw`}
            type="password"
            autoComplete="new-password"
            value={values.password}
            aria-invalid={errors.password ? true : undefined}
            onChange={(e) => onChange('password')(e.target.value)}
          />
          <span className={errors.password ? 'field__error' : 'field__hint'}>
            {errors.password ?? emptyHint}
          </span>
        </div>
        <div className="field">
          <label htmlFor={`${idPrefix}-pw2`}>Repeat password</label>
          <input
            id={`${idPrefix}-pw2`}
            type="password"
            autoComplete="new-password"
            value={values.repeat}
            disabled={!values.password}
            aria-invalid={errors.repeat ? true : undefined}
            onChange={(e) => onChange('repeat')(e.target.value)}
          />
          {errors.repeat && <span className="field__error">{errors.repeat}</span>}
        </div>
      </div>
      {values.password && (
        <label className="checkbox-line" htmlFor={`${idPrefix}-must`}>
          <input
            id={`${idPrefix}-must`}
            type="checkbox"
            checked={values.requireChange}
            onChange={(e) => onChange('requireChange')(e.target.checked)}
          />
          Ask them to choose their own password at first sign-in
        </label>
      )}
    </fieldset>
  );
}

/** Create (no `user`) or edit (with `user`) an account. */
function UserForm({ user = null, machines, onSaved, onCancel }) {
  const id = useId();
  const editing = user !== null;
  const [values, setValues] = useState({
    username: user?.username ?? '',
    displayName: user?.display_name ?? '',
    email: user?.email ?? '',
    role: user?.role ?? 'operator',
    machineIds: user?.machine_ids ?? [],
    password: '',
    repeat: '',
    requireChange: true,
  });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (field) => (value) => setValues((v) => ({ ...v, [field]: value }));

  const submit = async (event) => {
    event.preventDefault();
    const found = validateNewUser(editing ? { ...values, password: '', repeat: '' } : values);
    if (editing) delete found.username;
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError(null);
    const machineIds = values.role === 'operator' ? values.machineIds : [];
    try {
      if (editing) {
        const updated = await updateUser(user.id, {
          display_name: values.displayName.trim(),
          email: values.email.trim() || null,
          role: values.role,
          machine_ids: machineIds,
        });
        onSaved({ user: updated });
      } else {
        const created = await createUser({
          username: values.username.trim(),
          display_name: values.displayName.trim(),
          email: values.email.trim() || undefined,
          role: values.role,
          machine_ids: machineIds,
          ...(values.password
            ? { temporary_password: values.password, require_password_change: values.requireChange }
            : {}),
        });
        onSaved({ ...created, chosenPassword: Boolean(values.password), mustChange: created.user.must_change_password });
      }
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  const text = (field, label, props = {}) => (
    <div className="field">
      <label htmlFor={`${id}-${field}`}>{label}</label>
      <input
        id={`${id}-${field}`}
        value={values[field]}
        onChange={(e) => set(field)(e.target.value)}
        aria-invalid={errors[field] ? true : undefined}
        {...props}
      />
      {errors[field] && <span className="field__error">{errors[field]}</span>}
    </div>
  );

  return (
    <form className="user-form" onSubmit={submit} noValidate aria-label={editing ? `Edit ${user.username}` : 'New account'}>
      <div className="user-form__fields">
        {editing ? (
          <div className="field">
            <span className="field__label">Username</span>
            <span>{user.username} (cannot be changed)</span>
          </div>
        ) : (
          text('username', 'Username', { autoComplete: 'off', spellCheck: false })
        )}
        {text('displayName', 'Full name', { autoComplete: 'off' })}
        {text('email', 'Work email (optional)', { type: 'email', autoComplete: 'off' })}
        <div className="field">
          <label htmlFor={`${id}-role`}>Role</label>
          <select id={`${id}-role`} value={values.role} onChange={(e) => set('role')(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
          <span className="field__hint">{ROLES.find((r) => r.value === values.role)?.hint}</span>
        </div>
      </div>
      {values.role === 'operator' && (
        <MachinePicker machines={machines} selected={values.machineIds} onChange={set('machineIds')} idPrefix={`${id}-m`} />
      )}
      {!editing && (
        <PasswordFields
          idPrefix={`${id}-p`}
          values={values}
          errors={errors}
          onChange={set}
          emptyHint="Leave empty to get a one-time password instead."
        />
      )}
      {error && <ErrorCallout error={error} />}
      <div className="user-form__actions">
        <button type="submit" disabled={busy}>
          {busy ? 'Saving…' : editing ? 'Save changes' : 'Create account'}
        </button>
        <button type="button" className="button--ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** Reset someone's password: to one the admin chooses, or to a generated one-time password. */
function ResetPasswordForm({ user, onSaved, onCancel }) {
  const id = useId();
  const [values, setValues] = useState({ password: '', repeat: '', requireChange: true });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (field) => (value) => setValues((v) => ({ ...v, [field]: value }));

  const submit = async (event) => {
    event.preventDefault();
    const found = validateChosenPassword(values.password, values.repeat, user.username);
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError(null);
    try {
      const result = await resetUserPassword(user.id, {
        newPassword: values.password,
        requirePasswordChange: values.requireChange,
      });
      onSaved({ ...result, chosenPassword: Boolean(values.password), mustChange: result.user.must_change_password });
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  return (
    <form className="user-form" onSubmit={submit} noValidate aria-label={`Reset password for ${user.username}`}>
      <p className="muted small">{user.display_name} is signed out everywhere when you save.</p>
      <PasswordFields
        idPrefix={id}
        values={values}
        errors={errors}
        onChange={set}
        emptyHint="Leave empty to get a one-time password instead."
      />
      {error && <ErrorCallout error={error} />}
      <div className="user-form__actions">
        <button type="submit" disabled={busy}>
          {busy ? 'Saving…' : 'Reset password'}
        </button>
        <button type="button" className="button--ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** Inline confirmation for actions that end someone's sessions (no browser dialogs). */
function ConfirmAction({ label, question, onConfirm, danger = false }) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!asking) {
    return (
      <button type="button" className="button--ghost button--small" onClick={() => setAsking(true)}>
        {label}
      </button>
    );
  }
  return (
    <span className="confirm" role="group" aria-label={question}>
      <span className="small">{question}</span>
      <button
        type="button"
        className={`button--small ${danger ? 'button--danger' : ''}`}
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onConfirm();
          } finally {
            setBusy(false);
            setAsking(false);
          }
        }}
      >
        Yes, {label.toLowerCase()}
      </button>
      <button type="button" className="button--ghost button--small" onClick={() => setAsking(false)} disabled={busy}>
        Keep
      </button>
    </span>
  );
}

function UsersSection() {
  const { user: me } = useAuth();
  const [filters, setFilters] = useState({ q: '', role: '', active: '' });
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [mode, setMode] = useState({ kind: 'list' });
  const [oneTime, setOneTime] = useState(null);
  const [notice, setNotice] = useState(null);
  const [actionError, setActionError] = useState(null);

  const machines = useApiResource(({ signal }) => fetchMachines({ signal }), 'machines');
  const machineCodes = useMemo(
    () => new Map((machines.data ?? []).map((m) => [m.id, m.code])),
    [machines.data],
  );
  const params = {
    q: filters.q.trim() || null,
    role: filters.role || null,
    is_active: filters.active || null,
    limit: PAGE_SIZE,
    offset,
  };
  const users = useApiResource(({ signal }) => fetchUsers(params, { signal }), JSON.stringify([params, refresh]));

  const changeFilter = (field) => (value) => {
    setFilters((f) => ({ ...f, [field]: value }));
    setOffset(0);
  };
  const reload = () => setRefresh((n) => n + 1);

  const act = async (task) => {
    setActionError(null);
    try {
      const result = await task();
      if (result?.temporary_password) setOneTime(result);
      reload();
    } catch (err) {
      setActionError(err);
    }
  };

  const saved = (result) => {
    setMode({ kind: 'list' });
    setOneTime(null);
    setNotice(null);
    if (result?.temporary_password) setOneTime(result);
    else if (result?.chosenPassword) {
      setNotice(
        `Password set for ${result.user.username}. Tell ${result.user.display_name} the password you chose` +
          (result.mustChange ? '; they will choose their own at first sign-in.' : '.'),
      );
    }
    reload();
  };

  return (
    <>
      {oneTime && <OneTimePassword result={oneTime} onDismiss={() => setOneTime(null)} />}
      {notice && (
        <p className="callout callout--info" role="status">
          {notice}
        </p>
      )}
      {mode.kind === 'reset' && (
        <Card title={`Reset password for ${mode.user.username}`}>
          <ResetPasswordForm
            key={mode.user.id}
            user={mode.user}
            onSaved={saved}
            onCancel={() => setMode({ kind: 'list' })}
          />
        </Card>
      )}
      {(mode.kind === 'create' || mode.kind === 'edit') && (
        <Card title={mode.kind === 'create' ? 'New account' : `Edit ${mode.user.username}`}>
          <UserForm
            key={mode.kind === 'edit' ? mode.user.id : 'new'}
            user={mode.kind === 'edit' ? mode.user : null}
            machines={machines.data}
            onSaved={saved}
            onCancel={() => setMode({ kind: 'list' })}
          />
        </Card>
      )}
      <Card
        title="Accounts"
        subtitle="Only administrators can create accounts. There is no self sign-up."
        busy={users.loading}
        className="card--wide"
        actions={
          mode.kind === 'list' && (
            <button type="button" onClick={() => setMode({ kind: 'create' })}>
              New account
            </button>
          )
        }
      >
        <div className="toolbar">
          <span className="inline-field">
            <label htmlFor="user-search">Search</label>
            <input
              id="user-search"
              type="search"
              value={filters.q}
              maxLength={100}
              placeholder="Name, username or email"
              onChange={(e) => changeFilter('q')(e.target.value)}
            />
          </span>
          <InlineSelect label="Role" value={filters.role} onChange={changeFilter('role')} options={ROLE_FILTER} />
          <InlineSelect label="Status" value={filters.active} onChange={changeFilter('active')} options={STATUS_FILTER} />
        </div>
        {actionError && <ErrorCallout error={actionError} />}
        {users.error && <ErrorCallout error={users.error} onRetry={users.reload} />}
        {!users.error && !users.data && <LoadingState label="Loading accounts…" />}
        {users.data && users.data.total === 0 && <EmptyMessage>No accounts match these filters.</EmptyMessage>}
        {users.data && users.data.total > 0 && (
          <>
            <DataTable
              caption="Accounts"
              rows={users.data.items}
              columns={[
                {
                  key: 'name',
                  header: 'Person',
                  render: (row) => (
                    <span className="person">
                      <strong>{row.display_name}</strong>
                      <span className="muted small">
                        {row.username}
                        {row.email ? `, ${row.email}` : ''}
                      </span>
                    </span>
                  ),
                },
                { key: 'role', header: 'Role', render: (row) => roleLabel(row.role) },
                {
                  key: 'machines',
                  header: 'Machines',
                  render: (row) =>
                    row.role !== 'operator'
                      ? 'Whole plant'
                      : row.machine_ids.length
                        ? row.machine_ids.map((m) => machineCodes.get(m) ?? `#${m}`).join(', ')
                        : 'None',
                },
                { key: 'status', header: 'Status', render: (row) => <StatusBadge status={accountStatus(row)} /> },
                { key: 'last_login_at', header: 'Last sign-in', render: (row) => formatDateTime(row.last_login_at) },
                {
                  key: 'actions',
                  header: 'Actions',
                  render: (row) =>
                    row.id === me.id ? (
                      <span className="muted small">This is you</span>
                    ) : (
                      <span className="row-actions">
                        <button
                          type="button"
                          className="button--ghost button--small"
                          onClick={() => setMode({ kind: 'edit', user: row })}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="button--ghost button--small"
                          onClick={() => setMode({ kind: 'reset', user: row })}
                        >
                          Reset password
                        </button>
                        {row.is_active ? (
                          <ConfirmAction
                            label="Deactivate"
                            danger
                            question={`Deactivate ${row.username}? They are signed out at once.`}
                            onConfirm={() => act(() => setUserActive(row.id, false))}
                          />
                        ) : (
                          <button
                            type="button"
                            className="button--ghost button--small"
                            onClick={() => act(() => setUserActive(row.id, true))}
                          >
                            Reactivate
                          </button>
                        )}
                      </span>
                    ),
                },
              ]}
            />
            <Pagination
              label="Account pages"
              total={users.data.total}
              limit={users.data.limit}
              offset={users.data.offset}
              disabled={users.loading}
              onChange={setOffset}
            />
          </>
        )}
      </Card>
    </>
  );
}

const EVENT_TYPES = [
  '',
  'login_succeeded',
  'login_failed',
  'account_locked',
  'logout',
  'session_expired',
  'password_changed',
  'password_reset',
  'user_created',
  'user_updated',
  'user_deactivated',
  'user_reactivated',
  'admin_bootstrapped',
];

function AuditSection() {
  const { user } = useAuth();
  const [eventType, setEventType] = useState('');
  const [outcome, setOutcome] = useState('');
  const params = { event_type: eventType || null, success: outcome || null };
  const outcomeLabel = { true: 'succeeded only', false: 'failed only' }[outcome];
  return (
    <>
    <PrintHeader
      title="Access log"
      lines={[
        `Filters: ${eventType ? humanize(eventType) : 'all events'}${outcomeLabel ? `, ${outcomeLabel}` : ''}`,
        'Contains the rows shown on screen (use Next for further pages).',
      ]}
      generatedBy={user.display_name}
    />
    <PagedListCard
      title="Access log"
      subtitle="Sign-ins and account changes, newest first. Passwords and tokens are never recorded."
      actions={
        <>
          <InlineSelect
            label="Event"
            value={eventType}
            onChange={setEventType}
            options={EVENT_TYPES.map((t) => ({ value: t, label: t ? humanize(t) : 'All events' }))}
          />
          <InlineSelect
            label="Outcome"
            value={outcome}
            onChange={setOutcome}
            options={[
              { value: '', label: 'All' },
              { value: 'true', label: 'Succeeded' },
              { value: 'false', label: 'Failed' },
            ]}
          />
          <PrintButton title={pdfFileTitle('access log', new Date().toISOString().slice(0, 10))} />
        </>
      }
      scopeKey={JSON.stringify(params)}
      fetchPage={(page, options) => fetchAuditEvents({ ...params, ...page }, options)}
      caption="Access log"
      emptyText="No events match these filters."
      columns={[
        { key: 'created_at', header: 'When', render: (row) => formatDateTime(row.created_at) },
        { key: 'event_type', header: 'Event', render: (row) => humanize(row.event_type) },
        { key: 'outcome', header: 'Outcome', render: (row) => <StatusBadge status={row.success ? 'event_ok' : 'event_failed'} /> },
        { key: 'actor', header: 'By', render: (row) => row.actor_username ?? '—' },
        { key: 'target', header: 'Account', render: (row) => row.target_username ?? '—' },
        {
          key: 'details',
          header: 'Details',
          render: (row) =>
            Object.entries(row.details ?? {})
              .map(([k, v]) => `${humanize(k)}: ${Array.isArray(v) ? v.join(', ') : String(v)}`)
              .join('; ') || '—',
        },
      ]}
    />
    </>
  );
}

/** Admin: accounts, roles, machine assignments and the access log. */
export function AdminPage() {
  const [tab, setTab] = useState('users');
  return (
    <div className="dashboard">
      <header className="page-header no-print">
        <div>
          <h2 className="page-title">Users &amp; access</h2>
          <p className="page-subtitle">Create accounts, set roles and machines, and review sign-in activity.</p>
        </div>
        <div className="segmented no-print" role="tablist" aria-label="Administration sections">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'users'}
            className={tab === 'users' ? '' : 'button--ghost'}
            onClick={() => setTab('users')}
          >
            Accounts
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'audit'}
            className={tab === 'audit' ? '' : 'button--ghost'}
            onClick={() => setTab('audit')}
          >
            Access log
          </button>
        </div>
      </header>
      {tab === 'users' ? <UsersSection /> : <AuditSection />}
    </div>
  );
}