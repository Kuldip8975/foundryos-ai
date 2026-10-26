import { useId } from 'react';
import { DATE_PRESETS } from '../../lib/dates.js';

const DATA_SOURCES = [
  { value: '', label: 'All sources' },
  { value: 'manual', label: 'Manual entry' },
  { value: 'import', label: 'Imported' },
  { value: 'synthetic', label: 'Synthetic (demo)' },
];

function Select({ label, value, onChange, options, disabled, placeholder }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/**
 * Dashboard filters. Controlled: every change is reported through
 * `onChange(patch)`; the parent owns validation and loading.
 *
 * Shift options come from the analytics response; machines and products from
 * their list endpoints. If a list cannot be loaded the select is disabled and
 * says so, rather than offering made-up options.
 */
export function FilterBar({ filters, onChange, onReset, options, rangeError }) {
  const fromId = useId();
  const toId = useId();
  const errorId = useId();
  const { machines, products, shifts } = options;

  return (
    <form className="filters" aria-label="Dashboard filters" onSubmit={(e) => e.preventDefault()}>
      <Select
        label="Period"
        value={filters.preset}
        onChange={(preset) => onChange({ preset })}
        options={DATE_PRESETS}
      />
      <div className="field">
        <label htmlFor={fromId}>From</label>
        <input
          id={fromId}
          type="date"
          value={filters.dateFrom}
          max={filters.dateTo || undefined}
          onChange={(e) => onChange({ preset: 'custom', dateFrom: e.target.value })}
          aria-invalid={rangeError ? true : undefined}
          aria-describedby={rangeError ? errorId : undefined}
        />
      </div>
      <div className="field">
        <label htmlFor={toId}>To</label>
        <input
          id={toId}
          type="date"
          value={filters.dateTo}
          min={filters.dateFrom || undefined}
          onChange={(e) => onChange({ preset: 'custom', dateTo: e.target.value })}
          aria-invalid={rangeError ? true : undefined}
          aria-describedby={rangeError ? errorId : undefined}
        />
      </div>
      <Select
        label="Shift"
        value={filters.shift}
        onChange={(shift) => onChange({ shift })}
        placeholder="All shifts"
        options={shifts.map((shift) => ({ value: shift, label: `Shift ${shift}` }))}
      />
      <Select
        label="Machine"
        value={filters.machineId}
        onChange={(machineId) => onChange({ machineId })}
        placeholder={machines.error ? 'Machines unavailable' : 'All machines'}
        disabled={Boolean(machines.error)}
        options={(machines.data ?? []).map((m) => ({
          value: String(m.id),
          label: `${m.code} · ${m.name}${m.is_active ? '' : ' (inactive)'}`,
        }))}
      />
      <Select
        label="Product"
        value={filters.productId}
        onChange={(productId) => onChange({ productId })}
        placeholder={products.error ? 'Products unavailable' : 'All products'}
        disabled={Boolean(products.error)}
        options={(products.data ?? []).map((p) => ({
          value: String(p.id),
          label: `${p.part_number} · ${p.name}${p.is_active ? '' : ' (inactive)'}`,
        }))}
      />
      <Select
        label="Data source"
        value={filters.dataSource}
        onChange={(dataSource) => onChange({ dataSource })}
        options={DATA_SOURCES}
      />
      <div className="field field--action">
        <button type="button" className="button button--ghost" onClick={onReset}>
          Reset filters
        </button>
      </div>
      {rangeError && (
        <p id={errorId} className="filters__error" role="alert">
          {rangeError}
        </p>
      )}
    </form>
  );
}