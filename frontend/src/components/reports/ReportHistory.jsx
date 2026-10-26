import { useId, useState } from 'react';
import { fetchShiftReports } from '../../api/shiftReports.js';
import { validateDateRange } from '../../lib/dates.js';
import { formatDate, formatDateTime } from '../../lib/format.js';
import { StatusBadge } from '../StatusBadge.jsx';
import { InlineSelect, PagedListCard } from '../dashboard/PagedListCard.jsx';

const STATUSES = [
  { value: '', label: 'All' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'pending', label: 'Generating' },
];

/** Saved report history with date, shift and status filters. */
export function ReportHistory({ refreshToken, selectedId, onSelect }) {
  const ids = { from: useId(), to: useId(), shift: useId() };
  const [filters, setFilters] = useState({ dateFrom: '', dateTo: '', shift: '', status: '' });
  const set = (patch) => setFilters((current) => ({ ...current, ...patch }));
  const rangeError = validateDateRange(filters.dateFrom, filters.dateTo);
  const shiftValid = !filters.shift || /^[A-Za-z0-9_-]{1,16}$/.test(filters.shift);

  const params = {
    date_from: filters.dateFrom || null,
    date_to: filters.dateTo || null,
    shift: shiftValid ? filters.shift || null : null,
    status: filters.status || null,
  };

  return (
    <div className="report-history">
      <div className="history-filters" role="group" aria-label="Report history filters">
        <span className="inline-field">
          <label htmlFor={ids.from}>From</label>
          <input id={ids.from} type="date" value={filters.dateFrom} onChange={(e) => set({ dateFrom: e.target.value })} />
        </span>
        <span className="inline-field">
          <label htmlFor={ids.to}>To</label>
          <input id={ids.to} type="date" value={filters.dateTo} onChange={(e) => set({ dateTo: e.target.value })} />
        </span>
        <span className="inline-field">
          <label htmlFor={ids.shift}>Shift</label>
          <input
            id={ids.shift}
            type="text"
            size={6}
            maxLength={16}
            value={filters.shift}
            aria-invalid={shiftValid ? undefined : true}
            onChange={(e) => set({ shift: e.target.value.trim() })}
          />
        </span>
        <InlineSelect label="Status" value={filters.status} onChange={(status) => set({ status })} options={STATUSES} />
      </div>
      {(rangeError || !shiftValid) && (
        <p className="filters__error" role="alert">
          {rangeError ?? 'Shift codes use letters, digits, "-" or "_".'}
        </p>
      )}
      {!rangeError && (
        <PagedListCard
          title="Report history"
          subtitle="Newest first. Select a report to view it."
          scopeKey={JSON.stringify([params, refreshToken])}
          fetchPage={(page, options) => fetchShiftReports({ ...params, ...page }, options)}
          caption="Saved shift reports"
          emptyText="No saved reports match these filters."
          columns={[
            { key: 'production_date', header: 'Date', render: (row) => formatDate(row.production_date) },
            { key: 'shift', header: 'Shift' },
            { key: 'status', header: 'Status', render: (row) => <StatusBadge status={`report_${row.status}`} /> },
            {
              key: 'data',
              header: 'Data',
              render: (row) => (row.includes_synthetic_data ? 'Includes synthetic' : 'Recorded data'),
            },
            { key: 'created_at', header: 'Created', render: (row) => formatDateTime(row.created_at) },
            {
              key: 'view',
              header: 'Report',
              render: (row) => (
                <button
                  type="button"
                  className="button button--ghost button--small"
                  aria-pressed={row.id === selectedId}
                  aria-label={`View report ${row.id} (shift ${row.shift}, ${formatDate(row.production_date)})`}
                  onClick={() => onSelect(row.id)}
                >
                  View
                </button>
              ),
            },
          ]}
        />
      )}
    </div>
  );
}