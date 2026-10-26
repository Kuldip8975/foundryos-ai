import { describe, expect, it } from 'vitest';
import { buildShiftWindow } from './shiftWindow.js';
import { flattenMetrics, formatMetricValue } from './evidence.js';
import { describeApiError } from './errors.js';
import { validateShiftForm } from '../components/reports/ShiftReportForm.jsx';
import { METRICS } from '../test/reportFixtures.js';

describe('buildShiftWindow', () => {
  it('returns no window when both times are empty', () => {
    expect(buildShiftWindow('2026-01-10', '', '')).toEqual({ window: null, error: null });
  });

  it('converts local times on the production date into UTC instants', () => {
    const { window, error } = buildShiftWindow('2026-01-10', '06:00', '14:00');
    expect(error).toBeNull();
    expect(window.window_start).toBe(new Date(2026, 0, 10, 6, 0).toISOString());
    expect(window.window_end).toBe(new Date(2026, 0, 10, 14, 0).toISOString());
  });

  it('treats an end time at or before the start as the next day', () => {
    const overnight = buildShiftWindow('2026-01-10', '22:00', '06:00').window;
    expect(overnight.window_end).toBe(new Date(2026, 0, 11, 6, 0).toISOString());
    const fullDay = buildShiftWindow('2026-01-10', '06:00', '06:00').window;
    expect(new Date(fullDay.window_end) - new Date(fullDay.window_start)).toBe(24 * 3600 * 1000);
  });

  it('rejects partial or malformed input', () => {
    expect(buildShiftWindow('2026-01-10', '06:00', '').error).toMatch(/both a start and an end/);
    expect(buildShiftWindow('', '06:00', '14:00').error).toMatch(/production date/);
    expect(buildShiftWindow('2026-01-10', '6am', '14:00').error).toMatch(/HH:MM/);
  });
});

describe('validateShiftForm', () => {
  const base = { productionDate: '2026-01-10', shift: ' A ', startTime: '', endTime: '', dataSource: '' };

  it('accepts a valid form and trims the shift code', () => {
    const { scope, errors } = validateShiftForm(base);
    expect(errors).toEqual({});
    expect(scope).toEqual({ productionDate: '2026-01-10', shift: 'A', window: null, dataSource: '' });
  });

  it('reports every problem at once', () => {
    const { scope, errors } = validateShiftForm({ ...base, productionDate: '', shift: 'night shift', startTime: '06:00' });
    expect(scope).toBeNull();
    expect(Object.keys(errors).sort()).toEqual(['productionDate', 'shift', 'window']);
  });
});

describe('evidence lookup', () => {
  it('flattens metrics with the same keys as the backend', () => {
    const flat = flattenMetrics(METRICS);
    expect(flat['production.actual_quantity']).toBe(820);
    expect(flat['downtime.by_machine.0.downtime_seconds']).toBe(5400);
    expect(flat['previous.production.actual_quantity']).toBe(900);
    expect(flat['limitations.0']).toMatch(/pending inspection/);
  });

  it('formats values by meaning', () => {
    expect(formatMetricValue('production.target_achievement', 0.8631)).toBe('86.3%');
    expect(formatMetricValue('comparison.rejection_rate_change', 0.0102)).toBe('+1.0 pp');
    expect(formatMetricValue('comparison.defect_rate_change', -0.02)).toBe('-2.0 pp');
    expect(formatMetricValue('downtime.downtime_seconds', 5400)).toBe('1 h 30 min');
    expect(formatMetricValue('comparison.downtime_seconds_change', -1800)).toBe('-30 min');
    expect(formatMetricValue('comparison.actual_quantity_change', 15)).toBe('+15');
    expect(formatMetricValue('quality.defect_rate', null)).toBe('not available');
    expect(formatMetricValue('defects_by_category', [])).toBe('none');
  });
});

describe('AI error messages', () => {
  it('gives specific titles for AI and duplicate errors', () => {
    const notConfigured = describeApiError({ kind: 'http', status: 503, code: 'ai_not_configured', message: 'm' });
    expect(notConfigured.title).toBe('AI reports are not configured on the server');
    const busy = describeApiError({ kind: 'http', status: 409, code: 'report_in_progress', message: 'm' });
    expect(busy).toMatchObject({ title: 'A report for this shift is already being generated', validation: true });
  });

  it('keeps the existing messages for other errors', () => {
    expect(describeApiError({ kind: 'http', status: 422, code: 'invalid_date_range', message: 'm' }).title).toBe(
      'The filters were rejected',
    );
  });
});