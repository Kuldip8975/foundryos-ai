import { useEffect, useId, useState } from 'react';
import { formatUtcOffset, utcOffsetMinutes, validateDateRange } from '../../lib/dates.js';
import { buildShiftWindow } from '../../lib/shiftWindow.js';

const SHIFT_CODE = /^[A-Za-z0-9_-]{1,16}$/;

/** Validate the form; returns { scope, errors }. */
export function validateShiftForm(form) {
  const errors = {};
  if (!form.productionDate) errors.productionDate = 'Choose a production date.';
  else if (validateDateRange(form.productionDate, '')) errors.productionDate = 'Enter a valid date.';
  if (!SHIFT_CODE.test(form.shift.trim())) {
    errors.shift = 'Enter a shift code: letters, digits, "-" or "_" (max 16).';
  }
  const { window, error } = buildShiftWindow(form.productionDate, form.startTime, form.endTime);
  if (error) errors.window = error;
  if (Object.keys(errors).length) return { scope: null, errors };
  return {
    scope: {
      productionDate: form.productionDate,
      shift: form.shift.trim(),
      window,
      dataSource: form.dataSource,
    },
    errors,
  };
}

function Field({ id, label, error, hint, children }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children}
      {hint && !error && <span className="field__hint">{hint}</span>}
      {error && (
        <span id={`${id}-error`} className="field__error">
          {error}
        </span>
      )}
    </div>
  );
}

/**
 * Shift report request form. Validation happens here before any request;
 * the server validates again.
 */
export function ShiftReportForm({ initialDate = '', shiftOptions = [], busy, onPreview, onGenerate }) {
  const ids = { date: useId(), shift: useId(), start: useId(), end: useId(), source: useId(), list: useId() };
  const [form, setForm] = useState({
    productionDate: initialDate,
    shift: '',
    startTime: '',
    endTime: '',
    dataSource: '',
    regenerate: false,
  });
  const [errors, setErrors] = useState({});
  const set = (patch) => setForm((current) => ({ ...current, ...patch }));

  // Default the date to the latest day with data once it is known (never overwrite input).
  useEffect(() => {
    if (initialDate) setForm((current) => (current.productionDate ? current : { ...current, productionDate: initialDate }));
  }, [initialDate]);

  function submit(action) {
    const result = validateShiftForm(form);
    setErrors(result.errors);
    if (!result.scope) return;
    if (action === 'preview') onPreview(result.scope);
    else onGenerate(result.scope, { regenerate: form.regenerate });
  }

  // Which input shows each error message (Field renders it as `${inputId}-error`).
  const errorInput = { productionDate: ids.date, shift: ids.shift, window: ids.start };
  const invalid = (name) =>
    errors[name] ? { 'aria-invalid': true, 'aria-describedby': `${errorInput[name]}-error` } : {};

  return (
    <form
      className="report-form"
      aria-label="Shift report request"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit('generate');
      }}
    >
      <div className="report-form__grid">
        <Field id={ids.date} label="Production date" error={errors.productionDate}>
          <input
            id={ids.date}
            type="date"
            value={form.productionDate || ''}
            onChange={(e) => set({ productionDate: e.target.value })}
            required
            {...invalid('productionDate')}
          />
        </Field>
        <Field id={ids.shift} label="Shift" error={errors.shift}>
          <input
            id={ids.shift}
            type="text"
            value={form.shift}
            maxLength={16}
            list={ids.list}
            placeholder="e.g. A"
            autoComplete="off"
            onChange={(e) => set({ shift: e.target.value })}
            required
            {...invalid('shift')}
          />
          <datalist id={ids.list}>
            {shiftOptions.map((code) => (
              <option key={code} value={code} />
            ))}
          </datalist>
        </Field>
        <Field
          id={ids.start}
          label="Shift start (optional)"
          error={errors.window}
          hint={`Local time, ${formatUtcOffset(utcOffsetMinutes(form.productionDate || null))}`}
        >
          <input
            id={ids.start}
            type="time"
            value={form.startTime}
            onChange={(e) => set({ startTime: e.target.value })}
            {...invalid('window')}
          />
        </Field>
        <Field id={ids.end} label="Shift end (optional)" hint="Earlier than start = next day">
          <input id={ids.end} type="time" value={form.endTime} onChange={(e) => set({ endTime: e.target.value })} />
        </Field>
        <Field id={ids.source} label="Data source">
          <select id={ids.source} value={form.dataSource} onChange={(e) => set({ dataSource: e.target.value })}>
            <option value="">All sources</option>
            <option value="manual">Manual entry</option>
            <option value="import">Imported</option>
            <option value="synthetic">Synthetic (demo)</option>
          </select>
        </Field>
      </div>
      <p className="muted small">
        Without a shift window, downtime cannot be calculated and the report will say so.
      </p>
      <div className="report-form__actions">
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.regenerate}
            onChange={(e) => set({ regenerate: e.target.checked })}
          />
          Generate a new report even if the data is unchanged
        </label>
        <div className="report-form__buttons">
          <button type="button" className="button button--ghost" disabled={busy} onClick={() => submit('preview')}>
            Preview metrics
          </button>
          <button type="submit" className="button" disabled={busy}>
            {busy === 'generate' ? 'Generating…' : 'Generate AI report'}
          </button>
        </div>
      </div>
    </form>
  );
}