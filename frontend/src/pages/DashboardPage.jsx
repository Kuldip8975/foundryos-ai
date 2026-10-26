import { useCallback, useMemo, useState } from 'react';
import {
  dashboardParams,
  fetchDashboardSummary,
  fetchMachines,
  fetchProducts,
} from '../api/manufacturing.js';
import { useOptionalAuth } from '../auth/AuthContext.jsx';
import { PrintButton, PrintHeader } from '../components/PrintButton.jsx';
import { FilterBar } from '../components/dashboard/FilterBar.jsx';
import { KpiGrid } from '../components/dashboard/KpiGrid.jsx';
import { MaintenanceSummary } from '../components/dashboard/MaintenanceSummary.jsx';
import { DowntimeEventsTable, MaintenanceRequestsTable } from '../components/dashboard/OperationsTables.jsx';
import { EmptyState } from '../components/EmptyState.jsx';
import { BarList } from '../components/ui/BarList.jsx';
import { Card } from '../components/ui/Card.jsx';
import { EmptyMessage, ErrorCallout, LoadingState } from '../components/ui/StateViews.jsx';
import { TrendChart } from '../components/ui/TrendChart.jsx';
import { useApiResource } from '../hooks/useApiResource.js';
import { formatUtcOffset, presetRange, utcOffsetMinutes, validateDateRange } from '../lib/dates.js';
import {
  formatCompact,
  formatDateRange,
  formatDateTime,
  formatDuration,
  formatNumber,
  formatPercent,
  pluralize,
} from '../lib/format.js';
import { computeKpis, isSummaryEmpty, trendRows } from '../lib/kpi.js';
import { pdfFileTitle } from '../lib/print.js';

export const INITIAL_FILTERS = Object.freeze({
  preset: 'all',
  dateFrom: '',
  dateTo: '',
  shift: '',
  machineId: '',
  productId: '',
  dataSource: '',
});

const GRANULARITY_LABEL = { day: 'day', week: 'week (Mon–Sun)', month: 'month' };

const PRODUCTION_SERIES = [
  { key: 'actual', label: 'Actual output', color: 'var(--series-1)' },
  { key: 'target', label: 'Target', color: 'var(--series-ref)' },
];
const DEFECT_SERIES = [{ key: 'defectRate', label: 'Defect rate', color: 'var(--series-2)' }];

/** Apply a filter change, keeping presets and explicit dates consistent. */
export function applyFilterChange(filters, patch, today = new Date()) {
  const next = { ...filters, ...patch };
  if (patch.preset && patch.preset !== 'custom') {
    const range = presetRange(patch.preset, today);
    next.dateFrom = range.from;
    next.dateTo = range.to;
  }
  return next;
}

export function DashboardPage() {
  const [filters, setFilters] = useState(INITIAL_FILTERS);
  const [refreshToken, setRefreshToken] = useState(0);

  const rangeError = validateDateRange(filters.dateFrom, filters.dateTo);
  const offsetMinutes = utcOffsetMinutes(filters.dateFrom || null);
  const params = useMemo(() => dashboardParams(filters, offsetMinutes), [filters, offsetMinutes]);

  const summary = useApiResource(
    ({ signal }) => fetchDashboardSummary(params, { signal }),
    JSON.stringify([params, refreshToken]),
    { enabled: !rangeError },
  );
  const machines = useApiResource(({ signal }) => fetchMachines({ signal }), `machines|${refreshToken}`);
  const products = useApiResource(({ signal }) => fetchProducts({ signal }), `products|${refreshToken}`);

  const onChange = useCallback((patch) => setFilters((current) => applyFilterChange(current, patch)), []);
  const onReset = useCallback(() => setFilters(INITIAL_FILTERS), []);
  const refresh = useCallback(() => setRefreshToken((n) => n + 1), []);

  const machineLabel = useMemo(() => {
    const byId = new Map((machines.data ?? []).map((m) => [m.id, m.code]));
    return (id) => byId.get(id) ?? `Machine #${id}`;
  }, [machines.data]);

  const data = summary.data;
  const kpis = data ? computeKpis(data) : null;
  const rows = data ? trendRows(data.trend.points) : [];
  const granularity = data?.trend.granularity ?? 'day';
  const syntheticRows = data?.data_sources.synthetic ?? 0;
  const empty = data ? isSummaryEmpty(data) : false;
  const tableScope = {
    dateFrom: filters.dateFrom,
    dateTo: filters.dateTo,
    machineId: filters.machineId,
    dataSource: filters.dataSource,
    refreshToken,
  };

  const auth = useOptionalAuth();
  const machineName = filters.machineId
    ? (machines.data ?? []).find((m) => String(m.id) === String(filters.machineId))?.code
    : null;
  const productName = filters.productId
    ? (products.data ?? []).find((p) => String(p.id) === String(filters.productId))?.part_number
    : null;
  const printFilters = [
    filters.shift && `shift ${filters.shift}`,
    machineName && `machine ${machineName}`,
    productName && `product ${productName}`,
    filters.dataSource && `data source: ${filters.dataSource}`,
  ].filter(Boolean);

  return (
    <div className="dashboard" aria-busy={summary.loading}>
      <PrintHeader
        title="Manufacturing dashboard"
        lines={[
          `Period: ${formatDateRange(filters.dateFrom, filters.dateTo)}`,
          printFilters.length ? `Filters: ${printFilters.join(', ')}` : 'Filters: none (all machines, shifts and products)',
        ]}
        generatedBy={auth?.user?.display_name}
      />
      <header className="page-header">
        <div>
          <h2 className="page-title">Manufacturing dashboard</h2>
          <p className="page-subtitle">
            {formatDateRange(filters.dateFrom, filters.dateTo)} · Dates are plant calendar days; times shown in{' '}
            {formatUtcOffset(offsetMinutes)}
          </p>
        </div>
        <div className="page-header__actions">
          {data && <span className="muted small">Updated {formatDateTime(data.generated_at)}</span>}
          <button type="button" className="button no-print" onClick={refresh} disabled={summary.loading}>
            {summary.loading ? 'Refreshing…' : 'Refresh'}
          </button>
          <PrintButton
            title={pdfFileTitle('dashboard', filters.dateFrom || 'all dates', filters.dateTo, filters.shift && `shift ${filters.shift}`)}
            disabled={!data}
          />
        </div>
      </header>

      <FilterBar
        filters={filters}
        onChange={onChange}
        onReset={onReset}
        rangeError={rangeError}
        options={{ machines, products, shifts: data?.shifts ?? [] }}
      />

      {(machines.error || products.error) && (
        <p className="callout callout--warn" role="status">
          Some filter options could not be loaded; the dashboard figures are unaffected.
        </p>
      )}

      {syntheticRows > 0 && (
        <div className="callout callout--info" role="note">
          <strong>Synthetic demonstration data.</strong> {formatNumber(syntheticRows)} of the records in view are
          synthetic sample data, not real company records. Set <em>Data source</em> to “Manual entry” to see only real
          entries.
        </div>
      )}

      {rangeError && <p className="muted">Correct the date range to update the dashboard.</p>}

      {summary.error && <ErrorCallout error={summary.error} onRetry={summary.reload} />}

      {!summary.error && !rangeError && empty && (
        <EmptyState title="No manufacturing data for these filters">
          <p>Nothing was recorded for the selected period and filters.</p>
          {data.data_range.first_date ? (
            <p>
              Data is available from {formatDateRange(data.data_range.first_date, data.data_range.last_date)}.{' '}
              <button
                type="button"
                className="button button--small"
                onClick={() =>
                  onChange({
                    preset: 'custom',
                    dateFrom: data.data_range.first_date,
                    dateTo: data.data_range.last_date,
                  })
                }
              >
                Show that period
              </button>
            </p>
          ) : (
            <p>Load production data through the API to populate this dashboard.</p>
          )}
        </EmptyState>
      )}

      {!summary.error && !rangeError && !empty && (
        <>
          <section aria-label="Key indicators">
            <KpiGrid kpis={kpis} />
          </section>

          <div className="grid grid--2">
            <Card
              title="Production output vs target"
              subtitle={`Units per ${GRANULARITY_LABEL[granularity]}, by production date`}
              busy={summary.loading}
            >
              {!data && <LoadingState label="Loading production trend…" />}
              {data && rows.length === 0 && <EmptyMessage>No production records in this period.</EmptyMessage>}
              {data && rows.length > 0 && (
                <TrendChart
                  rows={rows}
                  series={PRODUCTION_SERIES}
                  granularity={granularity}
                  formatValue={(v) => `${formatNumber(v)} units`}
                  formatTick={formatCompact}
                  ariaLabel={`Production output and target per ${granularity}`}
                />
              )}
            </Card>

            <Card
              title="Defect rate"
              subtitle={`Defects ÷ inspected units per ${GRANULARITY_LABEL[granularity]}`}
              busy={summary.loading}
            >
              {!data && <LoadingState label="Loading quality trend…" />}
              {data && !rows.some((r) => r.defectRate != null) && (
                <EmptyMessage>No inspections recorded for this period.</EmptyMessage>
              )}
              {data && rows.some((r) => r.defectRate != null) && (
                <TrendChart
                  rows={rows}
                  series={DEFECT_SERIES}
                  granularity={granularity}
                  formatValue={(v) => formatPercent(v)}
                  formatTick={(v) => formatPercent(v, 0)}
                  ariaLabel={`Defect rate per ${granularity}`}
                />
              )}
            </Card>

            <Card title="Defects by category" subtitle="Defective units found in inspection" busy={summary.loading}>
              {!data && <LoadingState label="Loading defect categories…" />}
              {data && data.defects_by_category.length === 0 && <EmptyMessage>No defects recorded.</EmptyMessage>}
              {data && data.defects_by_category.length > 0 && (
                <BarList
                  label="Defective units by category"
                  color="var(--series-2)"
                  rows={data.defects_by_category.map((c) => ({
                    id: c.defect_category_id ?? 'none',
                    label: c.code ? `${c.code} · ${c.name}` : c.name,
                    sublabel: pluralize(c.inspection_count, 'inspection'),
                    value: c.defect_quantity,
                    display: `${formatNumber(c.defect_quantity)} units`,
                  }))}
                />
              )}
            </Card>

            <Card
              title="Downtime by machine"
              subtitle={
                filters.shift || filters.productId
                  ? 'Machine-level: shift and product filters do not apply'
                  : 'Downtime overlapping the selected period'
              }
              busy={summary.loading}
            >
              {!data && <LoadingState label="Loading downtime…" />}
              {data && data.downtime.by_machine.length === 0 && (
                <EmptyMessage>No machine downtime in this period.</EmptyMessage>
              )}
              {data && data.downtime.by_machine.length > 0 && (
                <BarList
                  label="Downtime duration by machine"
                  color="var(--series-3)"
                  rows={data.downtime.by_machine.map((m) => ({
                    id: m.machine_id,
                    label: `${m.code} · ${m.name}`,
                    sublabel: `${pluralize(m.event_count, 'event')}${
                      m.ongoing_count ? ` · ${formatNumber(m.ongoing_count)} ongoing` : ''
                    }`,
                    value: m.downtime_seconds,
                    display: formatDuration(m.downtime_seconds),
                  }))}
                />
              )}
            </Card>

            <Card title="Maintenance backlog" subtitle="Current status of requests for machines in scope" busy={summary.loading}>
              {!data && <LoadingState label="Loading maintenance…" />}
              {data && <MaintenanceSummary maintenance={data.maintenance} />}
            </Card>
          </div>

          <DowntimeEventsTable scope={tableScope} machineLabel={machineLabel} />
          <MaintenanceRequestsTable scope={tableScope} machineLabel={machineLabel} />
        </>
      )}
    </div>
  );
}