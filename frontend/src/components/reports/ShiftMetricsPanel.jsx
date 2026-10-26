import { KpiCard } from '../ui/KpiCard.jsx';
import { formatDate, formatDateTime, formatDuration, formatNumber, formatPercent, pluralize } from '../../lib/format.js';
import { formatMetricValue } from '../../lib/evidence.js';

function Change({ label, metricKey, value }) {
  return (
    <li>
      <span className="muted">{label}</span> <strong>{formatMetricValue(metricKey, value)}</strong>
    </li>
  );
}

/**
 * The deterministic metrics for one shift (computed by the backend from
 * database records). These are measured values, not AI output.
 */
export function ShiftMetricsPanel({ metrics }) {
  const p = metrics.production;
  const q = metrics.quality;
  const d = metrics.downtime;
  const m = metrics.maintenance;
  const c = metrics.comparison;

  return (
    <div className="shift-metrics">
      <p className="muted small">
        Shift {metrics.shift} on {formatDate(metrics.production_date)}
        {metrics.window_start
          ? ` · window ${formatDateTime(metrics.window_start)} – ${formatDateTime(metrics.window_end)}`
          : ' · no time window'}
        {metrics.data_source_filter ? ` · ${metrics.data_source_filter} data only` : ''}
      </p>
      <div className="kpi-grid">
        <KpiCard
          label="Output"
          value={formatNumber(p.actual_quantity)}
          unit="units"
          detail={`Target ${formatNumber(p.target_quantity)} · ${pluralize(p.record_count, 'record')}`}
        />
        <KpiCard label="Target achievement" value={formatPercent(p.target_achievement)} detail="Actual ÷ target" />
        <KpiCard
          label="Rejection rate"
          value={formatPercent(p.rejection_rate)}
          detail={`${formatNumber(p.rejected_quantity)} rejected ÷ ${formatNumber(p.actual_quantity)} produced`}
        />
        <KpiCard
          label="Defect rate"
          value={formatPercent(q.defect_rate)}
          detail={`${formatNumber(q.defect_quantity)} defects in ${formatNumber(q.inspected_quantity)} inspected`}
        />
        <KpiCard
          label="Downtime"
          value={d.available ? formatDuration(d.downtime_seconds) : 'Not calculated'}
          detail={d.available ? `${pluralize(d.event_count, 'event')} · ${formatNumber(d.ongoing_count)} ongoing` : 'Needs a shift window'}
        />
        <KpiCard
          label="Open maintenance (now)"
          value={formatNumber(m.open_now)}
          detail={
            m.raised_in_window == null
              ? 'Current backlog'
              : `${pluralize(m.raised_in_window, 'request')} raised in window`
          }
        />
      </div>

      {c ? (
        <div className="comparison">
          <h4 className="subheading">Compared with shift {metrics.shift} on {formatDate(metrics.previous.production_date)}</h4>
          <ul className="comparison__list">
            <Change label="Output" metricKey="comparison.actual_quantity_change" value={c.actual_quantity_change} />
            <Change label="Target achievement" metricKey="comparison.target_achievement_change" value={c.target_achievement_change} />
            <Change label="Rejection rate" metricKey="comparison.rejection_rate_change" value={c.rejection_rate_change} />
            <Change label="Defect rate" metricKey="comparison.defect_rate_change" value={c.defect_rate_change} />
            <Change label="Downtime" metricKey="comparison.downtime_seconds_change" value={c.downtime_seconds_change} />
          </ul>
          <p className="muted small">pp = percentage points (difference between two percentages).</p>
        </div>
      ) : (
        <p className="muted small">No earlier shift with the same code to compare with.</p>
      )}

      {metrics.limitations.length > 0 && (
        <div className="limitations">
          <h4 className="subheading">Data limitations</h4>
          <ul>
            {metrics.limitations.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}