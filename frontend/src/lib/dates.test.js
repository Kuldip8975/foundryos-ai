import { describe, expect, it } from 'vitest';
import {
  addDays,
  formatUtcOffset,
  localDayEndISO,
  localDayStartISO,
  parseISODate,
  presetRange,
  toISODate,
  utcOffsetMinutes,
  validateDateRange,
} from './dates.js';

describe('calendar dates', () => {
  it('parses YYYY-MM-DD as a local date and rejects impossible dates', () => {
    const date = parseISODate('2026-01-05');
    expect([date.getFullYear(), date.getMonth(), date.getDate()]).toEqual([2026, 0, 5]);
    expect(parseISODate('2026-02-30')).toBeNull();
    expect(parseISODate('05/01/2026')).toBeNull();
    expect(parseISODate('')).toBeNull();
  });

  it('round-trips and adds days across month and year boundaries', () => {
    expect(toISODate(new Date(2026, 0, 5))).toBe('2026-01-05');
    expect(addDays('2026-01-31', 1)).toBe('2026-02-01');
    expect(addDays('2026-01-01', -1)).toBe('2025-12-31');
  });

  it('builds inclusive presets relative to today', () => {
    const today = new Date(2026, 0, 18, 15, 30);
    expect(presetRange('7d', today)).toEqual({ from: '2026-01-12', to: '2026-01-18' });
    expect(presetRange('30d', today)).toEqual({ from: '2025-12-20', to: '2026-01-18' });
    expect(presetRange('all', today)).toEqual({ from: '', to: '' });
    expect(presetRange('custom', today)).toBeNull();
  });

  it('validates ranges', () => {
    expect(validateDateRange('', '')).toBeNull();
    expect(validateDateRange('2026-01-05', '2026-01-05')).toBeNull();
    expect(validateDateRange('2026-01-06', '2026-01-05')).toMatch(/on or before/);
    expect(validateDateRange('2026-13-01', '')).toMatch(/not a valid date/);
  });
});

describe('timezone handling', () => {
  it('reports the browser UTC offset for the given date (east of UTC is positive)', () => {
    expect(utcOffsetMinutes('2026-01-10')).toBe(-new Date(2026, 0, 10).getTimezoneOffset());
  });

  it('formats offsets', () => {
    expect(formatUtcOffset(330)).toBe('UTC+05:30');
    expect(formatUtcOffset(-300)).toBe('UTC-05:00');
    expect(formatUtcOffset(0)).toBe('UTC+00:00');
  });

  it('converts a local calendar day into explicit UTC instants', () => {
    const start = localDayStartISO('2026-01-10');
    const end = localDayEndISO('2026-01-10');
    expect(start).toBe(new Date(2026, 0, 10).toISOString());
    expect(start.endsWith('Z')).toBe(true);
    expect(new Date(end).getTime() - new Date(start).getTime()).toBe(24 * 3600 * 1000 - 1);
    expect(localDayStartISO('bad')).toBeNull();
  });
});