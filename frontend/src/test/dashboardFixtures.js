/**
 * TEST FIXTURES ONLY — shaped exactly like the backend responses
 * (app/schemas/analytics.py, app/schemas/manufacturing.py). Never imported by
 * application code.
 */

export const SUMMARY = Object.freeze({
  generated_at: '2026-01-20T09:00:00Z',
  filters: {
    date_from: null, date_to: null, shift: null, machine_id: null, product_id: null,
    data_source: null, utc_offset_minutes: 330,
  },
  data_range: { first_date: '2026-01-05', last_date: '2026-01-07' },
  shifts: ['A', 'B'],
  data_sources: { manual: 0, import: 0, synthetic: 12 },
  production: {
    record_count: 6, target_quantity: 2000, actual_quantity: 1800,
    accepted_quantity: 1700, rejected_quantity: 60, pending_quantity: 40,
  },
  quality: { inspection_count: 6, inspected_quantity: 400, defect_quantity: 18 },
  trend: {
    granularity: 'day',
    points: [
      { period_start: '2026-01-05', record_count: 2, target_quantity: 700, actual_quantity: 650, accepted_quantity: 620, rejected_quantity: 20, inspected_quantity: 150, defect_quantity: 6 },
      { period_start: '2026-01-06', record_count: 2, target_quantity: 650, actual_quantity: 560, accepted_quantity: 520, rejected_quantity: 25, inspected_quantity: 120, defect_quantity: 9 },
      { period_start: '2026-01-07', record_count: 2, target_quantity: 650, actual_quantity: 590, accepted_quantity: 560, rejected_quantity: 15, inspected_quantity: 130, defect_quantity: 3 },
    ],
  },
  defects_by_category: [
    { defect_category_id: 1, code: 'SYN-DIM', name: 'Synthetic: dimensional', defect_quantity: 11, inspection_count: 3 },
    { defect_category_id: 2, code: 'SYN-SURF', name: 'Synthetic: surface finish', defect_quantity: 7, inspection_count: 2 },
  ],
  downtime: {
    window_start: null, window_end: '2026-01-20T09:00:00Z', event_count: 3, ongoing_count: 1,
    downtime_seconds: 12600,
    by_machine: [
      { machine_id: 1, code: 'SYN-CNC-01', name: 'Synthetic CNC Mill 01', event_count: 2, ongoing_count: 1, downtime_seconds: 9000 },
      { machine_id: 2, code: 'SYN-PRS-01', name: 'Synthetic Stamping Press 01', event_count: 1, ongoing_count: 0, downtime_seconds: 3600 },
    ],
  },
  maintenance: {
    by_status: { open: 2, in_progress: 1, resolved: 1, closed: 1, cancelled: 1 },
    open_by_priority: { low: 0, medium: 1, high: 1, critical: 1 },
    open_count: 3,
    raised_in_period: 6,
  },
});

export function emptySummary(overrides = {}) {
  return {
    ...SUMMARY,
    data_range: { first_date: null, last_date: null },
    shifts: [],
    data_sources: { manual: 0, import: 0, synthetic: 0 },
    production: {
      record_count: 0, target_quantity: 0, actual_quantity: 0,
      accepted_quantity: 0, rejected_quantity: 0, pending_quantity: 0,
    },
    quality: { inspection_count: 0, inspected_quantity: 0, defect_quantity: 0 },
    trend: { granularity: 'day', points: [] },
    defects_by_category: [],
    downtime: { window_start: null, window_end: '2026-01-20T09:00:00Z', event_count: 0, ongoing_count: 0, downtime_seconds: 0, by_machine: [] },
    maintenance: {
      by_status: { open: 0, in_progress: 0, resolved: 0, closed: 0, cancelled: 0 },
      open_by_priority: { low: 0, medium: 0, high: 0, critical: 0 },
      open_count: 0,
      raised_in_period: 0,
    },
    ...overrides,
  };
}

export const MACHINES = [
  { id: 1, code: 'SYN-CNC-01', name: 'Synthetic CNC Mill 01', description: null, is_active: true, data_source: 'synthetic', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
  { id: 2, code: 'SYN-PRS-01', name: 'Synthetic Stamping Press 01', description: null, is_active: true, data_source: 'synthetic', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
];

export const PRODUCTS = [
  { id: 1, part_number: 'SYN-PART-1001', name: 'Synthetic Bracket A', description: null, is_active: true, data_source: 'synthetic', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
];

export function downtimeEvent(id, overrides = {}) {
  return {
    id, external_ref: null, machine_id: 1, started_at: '2026-01-06T08:00:00Z', ended_at: '2026-01-06T09:00:00Z',
    status: 'resolved', reason: `Synthetic: stop ${id}`, notes: null, data_source: 'synthetic',
    created_at: '2026-01-06T09:00:00Z', updated_at: '2026-01-06T09:00:00Z', duration_seconds: 3600,
    ...overrides,
  };
}

export function maintenanceRequest(id, overrides = {}) {
  return {
    id, external_ref: null, machine_id: 2, issue_description: `Synthetic issue ${id}`, priority: 'high',
    status: 'open', resolution_notes: null, resolved_at: null, data_source: 'synthetic',
    created_at: '2026-01-07T08:00:00Z', updated_at: '2026-01-07T08:00:00Z',
    ...overrides,
  };
}

export function page(items, { total = items.length, limit = 10, offset = 0 } = {}) {
  return { items, total, limit, offset };
}