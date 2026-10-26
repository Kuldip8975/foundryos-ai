import { KpiCard } from '../ui/KpiCard.jsx';
import { formatDuration, formatNumber, formatPercent, pluralize } from '../../lib/format.js';

/** Executive KPI cards. `kpis` comes from computeKpis(summary); null while loading. */
export function KpiGrid({ kpis }) {
  const loading = !kpis;
  const k = kpis ?? {};
  return (
    <div className="kpi-grid">
      <KpiCard
        loading={loading}
        label="Total output"
        value={formatNumber(k.output)}
        unit="units"
        detail={pluralize(k.recordCount, 'production record')}
        definition="Sum of actual quantity produced."
      />
      <KpiCard
        loading={loading}
        label="Target achievement"
        value={formatPercent(k.targetAchievement)}
        detail={`Target ${formatNumber(k.target)} units`}
        definition="Actual output ÷ target quantity."
      />
      <KpiCard
        loading={loading}
        label="Accepted"
        value={formatNumber(k.accepted)}
        unit="units"
        detail={`First-pass yield ${formatPercent(k.firstPassYield)} · ${formatNumber(k.pending)} pending`}
        definition="Yield = accepted ÷ (accepted + rejected)."
      />
      <KpiCard
        loading={loading}
        label="Rejected"
        value={formatNumber(k.rejected)}
        unit="units"
        detail={`Rejection rate ${formatPercent(k.rejectionRate)} of output`}
        definition="Rejection rate = rejected ÷ actual output."
      />
      <KpiCard
        loading={loading}
        label="Defect rate"
        value={formatPercent(k.defectRate)}
        detail={`${formatNumber(k.defects)} defects in ${formatNumber(k.inspected)} inspected`}
        definition="Defects found ÷ units inspected."
      />
      <KpiCard
        loading={loading}
        label="Machine downtime"
        value={formatDuration(k.downtimeSeconds)}
        detail={`${pluralize(k.downtimeEvents, 'event')} · ${formatNumber(k.ongoingDowntime)} ongoing`}
        definition="Downtime overlapping the selected period, all machines in scope."
        tone={k.ongoingDowntime > 0 ? 'warn' : undefined}
      />
      <KpiCard
        loading={loading}
        label="Open maintenance"
        value={formatNumber(k.openMaintenance)}
        detail={`${formatNumber(k.criticalOpen)} critical · ${formatNumber(k.highOpen)} high priority`}
        definition="Requests currently open or in progress (not date-filtered)."
        tone={k.criticalOpen > 0 ? 'bad' : undefined}
      />
    </div>
  );
}