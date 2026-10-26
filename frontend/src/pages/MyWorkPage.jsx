import { useId, useMemo, useState } from 'react';
import { sendJson } from '../api/client.js';
import { fetchDowntimeEvents, fetchPage, fetchProducts } from '../api/manufacturing.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { DowntimeEventsTable, MaintenanceRequestsTable } from '../components/dashboard/OperationsTables.jsx';
import { PagedListCard } from '../components/dashboard/PagedListCard.jsx';
import { StatusBadge } from '../components/StatusBadge.jsx';
import { Card } from '../components/ui/Card.jsx';
import { ErrorCallout, LoadingState } from '../components/ui/StateViews.jsx';
import { useApiResource } from '../hooks/useApiResource.js';
import { ROUTES } from '../hooks/useHashRoute.js';
import { can } from '../lib/access.js';
import { toISODate } from '../lib/dates.js';
import { formatDate, formatDateTime, formatNumber } from '../lib/format.js';

const MAX_REASON = 500;

/** "2026-10-15T09:30" (datetime-local, the person's time zone) → ISO instant with offset. */
export function localInputToISO(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function nowForInput(now = new Date()) {
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

/** Checks mirroring the server's rules for a downtime report. */
export function validateDowntime({ machineId, startedAt, endedAt, reason }, now = new Date()) {
  const errors = {};
  if (!machineId) errors.machineId = 'Choose a machine.';
  const start = localInputToISO(startedAt);
  if (!start) errors.startedAt = 'Enter when the machine stopped.';
  else if (new Date(start) > new Date(now.getTime() + 5 * 60_000)) errors.startedAt = 'This time is in the future.';
  const end = localInputToISO(endedAt);
  if (endedAt && !end) errors.endedAt = 'Enter a valid time or leave it empty.';
  if (start && end && new Date(end) <= new Date(start)) errors.endedAt = 'It must restart after it stopped.';
  const text = (reason ?? '').trim();
  if (!text) errors.reason = 'Describe why the machine stopped.';
  else if (text.length > MAX_REASON) errors.reason = `Keep it under ${MAX_REASON} characters.`;
  return errors;
}

/** Checks mirroring the server's rules for a shift output record. */
export function validateOutput(values, today = toISODate(new Date())) {
  const errors = {};
  if (!values.machineId) errors.machineId = 'Choose a machine.';
  if (!values.productId) errors.productId = 'Choose a product.';
  if (!values.productionDate) errors.productionDate = 'Enter the production date.';
  else if (values.productionDate > today) errors.productionDate = 'The date cannot be in the future.';
  if (!/^[A-Za-z0-9_-]{1,16}$/.test((values.shift ?? '').trim())) errors.shift = 'Enter the shift code, e.g. A.';
  const numbers = {};
  for (const field of ['target', 'actual', 'accepted', 'rejected']) {
    const raw = values[field];
    const n = Number(raw);
    if (raw === '' || !Number.isInteger(n) || n < 0) errors[field] = 'Whole number, 0 or more.';
    numbers[field] = n;
  }
  if (!errors.accepted && !errors.rejected && !errors.actual && numbers.accepted + numbers.rejected > numbers.actual) {
    errors.accepted = 'Accepted + rejected cannot exceed actual output.';
  }
  return errors;
}

function Field({ id, label, error, hint, children }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children}
      {(error || hint) && (
        <span id={`${id}-note`} className={error ? 'field__error' : 'field__hint'}>
          {error ?? hint}
        </span>
      )}
    </div>
  );
}

function MachineSelect({ id, machines, value, onChange, error }) {
  return (
    <Field id={id} label="Machine" error={error}>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={error ? true : undefined}>
        <option value="">Choose…</option>
        {machines.map((m) => (
          <option key={m.id} value={m.id} disabled={!m.is_active}>
            {m.code} — {m.name}
            {m.is_active ? '' : ' (inactive)'}
          </option>
        ))}
      </select>
    </Field>
  );
}

function DowntimeForm({ machines, onSaved }) {
  const id = useId();
  const empty = { machineId: machines.length === 1 ? String(machines[0].id) : '', startedAt: nowForInput(), endedAt: '', reason: '' };
  const [values, setValues] = useState(empty);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(null);
  const set = (field) => (value) => setValues((v) => ({ ...v, [field]: value }));

  const submit = async (event) => {
    event.preventDefault();
    const found = validateDowntime(values);
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const { data } = await sendJson('/downtime-events', {
        body: {
          machine_id: Number(values.machineId),
          started_at: localInputToISO(values.startedAt),
          ended_at: localInputToISO(values.endedAt) ?? undefined,
          reason: values.reason.trim(),
        },
      });
      setSaved(data);
      setValues({ ...empty, machineId: values.machineId, startedAt: nowForInput() });
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="entry-form" onSubmit={submit} noValidate aria-label="Report downtime">
      <MachineSelect id={`${id}-m`} machines={machines} value={values.machineId} onChange={set('machineId')} error={errors.machineId} />
      <Field id={`${id}-s`} label="Stopped at" error={errors.startedAt}>
        <input id={`${id}-s`} type="datetime-local" value={values.startedAt} onChange={(e) => set('startedAt')(e.target.value)} aria-invalid={errors.startedAt ? true : undefined} />
      </Field>
      <Field id={`${id}-e`} label="Restarted at" error={errors.endedAt} hint="Leave empty while it is still down.">
        <input id={`${id}-e`} type="datetime-local" value={values.endedAt} onChange={(e) => set('endedAt')(e.target.value)} aria-invalid={errors.endedAt ? true : undefined} />
      </Field>
      <Field id={`${id}-r`} label="Reason" error={errors.reason}>
        <textarea id={`${id}-r`} rows={2} maxLength={MAX_REASON} value={values.reason} onChange={(e) => set('reason')(e.target.value)} aria-invalid={errors.reason ? true : undefined} />
      </Field>
      {error && <ErrorCallout error={error} />}
      {saved && (
        <p className="callout callout--info" role="status">
          Downtime recorded ({saved.status === 'ongoing' ? 'still down' : 'resolved'}).
        </p>
      )}
      <div>
        <button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Record downtime'}</button>
      </div>
    </form>
  );
}

function OutputForm({ machines, onSaved }) {
  const id = useId();
  const products = useApiResource(({ signal }) => fetchProducts({ signal }), 'products');
  const activeProducts = (products.data ?? []).filter((p) => p.is_active);
  const empty = {
    machineId: machines.length === 1 ? String(machines[0].id) : '',
    productId: '',
    productionDate: toISODate(new Date()),
    shift: '',
    target: '',
    actual: '',
    accepted: '',
    rejected: '',
  };
  const [values, setValues] = useState(empty);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const set = (field) => (value) => setValues((v) => ({ ...v, [field]: value }));

  const submit = async (event) => {
    event.preventDefault();
    const found = validateOutput(values);
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await sendJson('/production-records', {
        body: {
          production_date: values.productionDate,
          shift: values.shift.trim(),
          product_id: Number(values.productId),
          machine_id: Number(values.machineId),
          target_quantity: Number(values.target),
          actual_quantity: Number(values.actual),
          accepted_quantity: Number(values.accepted),
          rejected_quantity: Number(values.rejected),
        },
      });
      setSaved(true);
      setValues({ ...empty, machineId: values.machineId, productionDate: values.productionDate, shift: values.shift });
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const number = (field, label) => (
    <Field id={`${id}-${field}`} label={label} error={errors[field]}>
      <input
        id={`${id}-${field}`}
        type="number"
        min="0"
        step="1"
        inputMode="numeric"
        value={values[field]}
        onChange={(e) => set(field)(e.target.value)}
        aria-invalid={errors[field] ? true : undefined}
      />
    </Field>
  );

  return (
    <form className="entry-form entry-form--grid" onSubmit={submit} noValidate aria-label="Record shift output">
      <MachineSelect id={`${id}-m`} machines={machines} value={values.machineId} onChange={set('machineId')} error={errors.machineId} />
      <Field id={`${id}-p`} label="Product" error={errors.productId ?? (products.error ? 'Products could not be loaded.' : undefined)}>
        <select id={`${id}-p`} value={values.productId} onChange={(e) => set('productId')(e.target.value)} aria-invalid={errors.productId ? true : undefined}>
          <option value="">{products.loading ? 'Loading…' : 'Choose…'}</option>
          {activeProducts.map((p) => (
            <option key={p.id} value={p.id}>
              {p.part_number} — {p.name}
            </option>
          ))}
        </select>
      </Field>
      <Field id={`${id}-d`} label="Production date" error={errors.productionDate}>
        <input id={`${id}-d`} type="date" value={values.productionDate} onChange={(e) => set('productionDate')(e.target.value)} aria-invalid={errors.productionDate ? true : undefined} />
      </Field>
      <Field id={`${id}-sh`} label="Shift" error={errors.shift}>
        <input id={`${id}-sh`} type="text" maxLength={16} value={values.shift} onChange={(e) => set('shift')(e.target.value)} aria-invalid={errors.shift ? true : undefined} />
      </Field>
      {number('target', 'Target')}
      {number('actual', 'Actual output')}
      {number('accepted', 'Accepted')}
      {number('rejected', 'Rejected')}
      <div className="entry-form__footer">
        {error && <ErrorCallout error={error} />}
        {saved && (
          <p className="callout callout--info" role="status">
            Shift output recorded.
          </p>
        )}
        <button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Record output'}</button>
      </div>
    </form>
  );
}

function MachineStates({ machines, refreshToken }) {
  const ids = machines.map((m) => m.id);
  const ongoing = useApiResource(
    ({ signal }) => fetchDowntimeEvents({ status: 'ongoing', limit: 200 }, { signal }),
    `ongoing|${refreshToken}`,
  );
  if (ongoing.error) return <ErrorCallout error={ongoing.error} onRetry={ongoing.reload} />;
  if (!ongoing.data) return <LoadingState label="Loading machine states…" />;
  const down = new Map(ongoing.data.items.filter((e) => ids.includes(e.machine_id)).map((e) => [e.machine_id, e]));
  return (
    <ul className="machine-states" aria-label="Your machines">
      {machines.map((m) => {
        const event = down.get(m.id);
        return (
          <li key={m.id} className={`machine-state ${event ? 'machine-state--down' : ''}`}>
            <span className="machine-state__code">{m.code}</span>
            <span className="machine-state__name">{m.name}</span>
            {event ? (
              <span className="machine-state__detail">
                <StatusBadge status="ongoing" /> since {formatDateTime(event.started_at)}: {event.reason}
              </span>
            ) : (
              <span className="machine-state__detail muted">
                {m.is_active ? 'No ongoing downtime recorded' : 'Inactive'}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Operator start page: the machines assigned to this person, what is wrong
 * with them right now, and forms to record downtime and shift output. Every
 * list is already limited to these machines by the server.
 */
export function MyWorkPage() {
  const { user } = useAuth();
  const machines = user.machines ?? [];
  const [refreshToken, setRefreshToken] = useState(0);
  const refresh = () => setRefreshToken((n) => n + 1);
  const labels = useMemo(() => new Map(machines.map((m) => [m.id, `${m.code} — ${m.name}`])), [machines]);
  const machineLabel = (machineId) => labels.get(machineId) ?? `Machine #${machineId}`;
  const scope = { dateFrom: '', dateTo: '', machineId: '', dataSource: '', refreshToken };

  return (
    <div className="dashboard">
      <header className="page-header">
        <div>
          <h2 className="page-title">My machines</h2>
          <p className="page-subtitle">
            {machines.length
              ? `You record data for ${machines.map((m) => m.code).join(', ')}.`
              : 'Machines assigned to you appear here.'}
          </p>
        </div>
      </header>

      {machines.length === 0 ? (
        <section className="empty-state">
          <h2>No machines assigned yet</h2>
          <p className="muted">Ask your administrator to assign the machines you work on.</p>
        </section>
      ) : (
        <>
          <Card title="Right now" subtitle="Based on recorded downtime, not live machine signals">
            <MachineStates machines={machines} refreshToken={refreshToken} />
          </Card>
          <div className="entry-grid">
            {can(user, 'downtime:record') && (
              <Card title="Report downtime" subtitle="Times are in your local time zone">
                <DowntimeForm machines={machines} onSaved={refresh} />
              </Card>
            )}
            {can(user, 'production:record') && (
              <Card title="Record shift output">
                <OutputForm machines={machines} onSaved={refresh} />
              </Card>
            )}
          </div>
          {can(user, 'assistant:use') && (
            <p className="callout callout--info">
              Need maintenance? Ask the <a href={ROUTES.assistant}>workflow assistant</a> to prepare a request; a
              supervisor approves it before it is created.
            </p>
          )}
          <DowntimeEventsTable scope={scope} machineLabel={machineLabel} />
          <PagedListCard
            title="Shift output"
            subtitle="Production records for your machines, newest first"
            scopeKey={`output|${refreshToken}`}
            fetchPage={(page, options) => fetchPage('/production-records', page, options)}
            caption="Production records"
            emptyText="No shift output recorded yet."
            columns={[
              { key: 'date', header: 'Date', render: (row) => formatDate(row.production_date) },
              { key: 'shift', header: 'Shift' },
              { key: 'machine', header: 'Machine', render: (row) => (row.machine_id ? machineLabel(row.machine_id) : '—') },
              { key: 'actual', header: 'Actual', numeric: true, render: (row) => formatNumber(row.actual_quantity) },
              { key: 'accepted', header: 'Accepted', numeric: true, render: (row) => formatNumber(row.accepted_quantity) },
              { key: 'rejected', header: 'Rejected', numeric: true, render: (row) => formatNumber(row.rejected_quantity) },
            ]}
          />
          <MaintenanceRequestsTable scope={scope} machineLabel={machineLabel} />
        </>
      )}
    </div>
  );
}