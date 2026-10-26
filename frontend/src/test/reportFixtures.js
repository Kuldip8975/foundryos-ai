/**
 * TEST FIXTURES ONLY — shaped exactly like app/schemas/shift_reports.py.
 * Never imported by application code.
 */

export const METRICS = Object.freeze({
  production_date: '2026-01-10',
  shift: 'A',
  window_start: '2026-01-10T00:30:00Z',
  window_end: '2026-01-10T08:30:00Z',
  data_source_filter: null,
  data_sources: { manual: 0, import: 0, synthetic: 9 },
  production: {
    record_count: 3, target_quantity: 950, actual_quantity: 820, accepted_quantity: 790,
    rejected_quantity: 22, pending_quantity: 8, target_achievement: 820 / 950,
    rejection_rate: 22 / 820, first_pass_yield: 790 / 812,
  },
  production_by_machine: [
    { machine: 'SYN-CNC-01', record_count: 1, target_quantity: 400, actual_quantity: 352, rejected_quantity: 9, target_achievement: 0.88, rejection_rate: 9 / 352 },
  ],
  quality: { inspection_count: 3, inspected_quantity: 180, defect_quantity: 9, defect_rate: 0.05 },
  defects_by_category: [{ category: 'SYN-DIM', defect_quantity: 6, inspection_count: 2 }],
  downtime: {
    available: true, event_count: 2, ongoing_count: 0, downtime_seconds: 5400,
    by_machine: [{ machine: 'SYN-CNC-01', event_count: 2, ongoing_count: 0, downtime_seconds: 5400 }],
    top_reasons: [{ reason: 'Synthetic: tool change', event_count: 2, downtime_seconds: 5400 }],
  },
  maintenance: { raised_in_window: 1, open_now: 3, open_now_by_priority: { low: 0, medium: 1, high: 1, critical: 1 } },
  previous: {
    production_date: '2026-01-09',
    production: {
      record_count: 3, target_quantity: 950, actual_quantity: 900, accepted_quantity: 880,
      rejected_quantity: 15, pending_quantity: 5, target_achievement: 900 / 950,
      rejection_rate: 15 / 900, first_pass_yield: 880 / 895,
    },
    quality: { inspection_count: 3, inspected_quantity: 180, defect_quantity: 4, defect_rate: 4 / 180 },
    downtime_seconds: 1800,
  },
  comparison: {
    actual_quantity_change: -80,
    target_achievement_change: 820 / 950 - 900 / 950,
    rejection_rate_change: 22 / 820 - 15 / 900,
    defect_rate_change: 0.05 - 4 / 180,
    downtime_seconds_change: 3600,
  },
  limitations: [
    '8 produced units are neither accepted nor rejected yet (pending inspection).',
    'Includes synthetic demonstration data; it does not describe real operations.',
  ],
});

export const CONTENT = Object.freeze({
  executive_summary: 'Synthetic data: output reached 86.3% of target, below the previous shift.',
  production_performance: [
    {
      statement: 'Output was 820 units against a target of 950.',
      kind: 'measured_fact',
      evidence: ['production.actual_quantity', 'production.target_quantity'],
    },
  ],
  quality_observations: [
    {
      statement: 'The higher defect rate may be related to dimensional issues.',
      kind: 'possible_explanation',
      evidence: ['quality.defect_rate', 'defects_by_category.0.defect_quantity'],
    },
  ],
  downtime_maintenance_observations: [
    { statement: 'Downtime was 1 h 30 min.', kind: 'measured_fact', evidence: ['downtime.downtime_seconds'] },
  ],
  recommendations: [
    {
      priority: 'high',
      action: 'Check SYN-CNC-01 tooling.',
      rationale: 'Most downtime and defects relate to it.',
      evidence: ['downtime.by_machine.0.downtime_seconds'],
    },
  ],
  data_limitations: ['Synthetic data only.'],
});

export function report(id = 1, overrides = {}) {
  return {
    id,
    production_date: '2026-01-10',
    shift: 'A',
    window_start: METRICS.window_start,
    window_end: METRICS.window_end,
    data_source: null,
    status: 'completed',
    provider: 'gemini',
    model: 'gemini-2.5-flash',
    prompt_version: 'shift-report-v1',
    error_code: null,
    error_message: null,
    includes_synthetic_data: true,
    created_at: '2026-01-10T09:00:00Z',
    completed_at: '2026-01-10T09:00:20Z',
    input_fingerprint: 'a'.repeat(64),
    metrics: METRICS,
    content: CONTENT,
    ...overrides,
  };
}

export function summary(fullReport) {
  const { input_fingerprint: _f, metrics: _m, content: _c, ...rest } = fullReport;
  return rest;
}