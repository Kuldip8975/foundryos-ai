import { BarList } from '../ui/BarList.jsx';
import { formatNumber, humanize, pluralize } from '../../lib/format.js';

const STATUS_ORDER = ['open', 'in_progress', 'resolved', 'closed', 'cancelled'];
const PRIORITY_ORDER = ['critical', 'high', 'medium', 'low'];
const PRIORITY_COLORS = {
  critical: 'var(--status-critical)',
  high: 'var(--status-serious)',
  medium: 'var(--status-warning)',
  low: 'var(--status-neutral)',
};

/** Backlog by status, and open requests by priority (from the analytics summary). */
export function MaintenanceSummary({ maintenance }) {
  return (
    <div className="maintenance-summary">
      <dl className="status-counts">
        {STATUS_ORDER.map((status) => (
          <div key={status} className={`status-counts__item status-counts__item--${status}`}>
            <dt>{humanize(status)}</dt>
            <dd>{formatNumber(maintenance.by_status[status] ?? 0)}</dd>
          </div>
        ))}
      </dl>
      <h4 className="subheading">Open and in-progress by priority</h4>
      <BarList
        label="Open maintenance requests by priority"
        rows={PRIORITY_ORDER.map((priority) => ({
          id: priority,
          label: humanize(priority),
          value: maintenance.open_by_priority[priority] ?? 0,
          display: formatNumber(maintenance.open_by_priority[priority] ?? 0),
          color: PRIORITY_COLORS[priority],
        }))}
      />
      <p className="muted small">
        {pluralize(maintenance.raised_in_period, 'request')} raised in the selected period.
      </p>
    </div>
  );
}