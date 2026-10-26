/**
 * KPI derivation from the /analytics/dashboard summary.
 *
 * The backend returns additive totals (sums and counts). Every ratio shown on
 * the dashboard is derived here from those totals — never averaged from
 * per-day ratios — so the figures stay exact for any filter. A ratio whose
 * denominator is zero is `null` ("not available"), not 0.
 */

/** numerator / denominator, or null when the denominator is 0 or missing. */
export function safeRatio(numerator, denominator) {
  if (typeof numerator !== 'number' || typeof denominator !== 'number') return null;
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || denominator <= 0) return null;
  return numerator / denominator;
}

/**
 * @param {object} summary DashboardSummary from the API
 */
export function computeKpis(summary) {
  const p = summary.production;
  const q = summary.quality;
  const d = summary.downtime;
  const m = summary.maintenance;
  const decided = p.accepted_quantity + p.rejected_quantity;

  return {
    recordCount: p.record_count,
    output: p.actual_quantity,
    target: p.target_quantity,
    /** actual ÷ target */
    targetAchievement: safeRatio(p.actual_quantity, p.target_quantity),
    accepted: p.accepted_quantity,
    rejected: p.rejected_quantity,
    pending: p.pending_quantity,
    /** accepted ÷ (accepted + rejected): share of decided units accepted first time */
    firstPassYield: safeRatio(p.accepted_quantity, decided),
    /** rejected ÷ actual output */
    rejectionRate: safeRatio(p.rejected_quantity, p.actual_quantity),
    inspected: q.inspected_quantity,
    defects: q.defect_quantity,
    inspectionCount: q.inspection_count,
    /** defects ÷ inspected units (inspection sample) */
    defectRate: safeRatio(q.defect_quantity, q.inspected_quantity),
    downtimeSeconds: d.downtime_seconds,
    downtimeEvents: d.event_count,
    ongoingDowntime: d.ongoing_count,
    openMaintenance: m.open_count,
    criticalOpen: m.open_by_priority?.critical ?? 0,
    highOpen: m.open_by_priority?.high ?? 0,
    raisedInPeriod: m.raised_in_period,
  };
}

/** Trend points with derived per-bucket ratios for charting. */
export function trendRows(points) {
  return points.map((point) => ({
    date: point.period_start,
    actual: point.actual_quantity,
    target: point.target_quantity,
    accepted: point.accepted_quantity,
    rejected: point.rejected_quantity,
    inspected: point.inspected_quantity,
    defects: point.defect_quantity,
    targetAchievement: safeRatio(point.actual_quantity, point.target_quantity),
    defectRate: safeRatio(point.defect_quantity, point.inspected_quantity),
  }));
}

/** True when the summary has nothing at all to show for the current filters. */
export function isSummaryEmpty(summary) {
  return (
    summary.production.record_count === 0 &&
    summary.quality.inspection_count === 0 &&
    summary.downtime.event_count === 0 &&
    Object.values(summary.maintenance.by_status).every((count) => count === 0)
  );
}