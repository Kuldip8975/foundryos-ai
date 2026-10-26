import { describe, expect, it } from 'vitest';
import {
  MISSING,
  formatCompact,
  formatDate,
  formatDateRange,
  formatDateTime,
  formatDuration,
  formatNumber,
  formatPercent,
  formatPeriod,
  humanize,
  pluralize,
} from './format.js';

describe('number formatting', () => {
  it('groups thousands and shows missing values as a dash, never as 0', () => {
    expect(formatNumber(1234567)).toBe('1,234,567');
    expect(formatNumber(0)).toBe('0');
    expect(formatNumber(null)).toBe(MISSING);
    expect(formatNumber(Number.NaN)).toBe(MISSING);
  });

  it('formats ratios as percentages', () => {
    expect(formatPercent(0.045)).toBe('4.5%');
    expect(formatPercent(0.9, 0)).toBe('90%');
    expect(formatPercent(null)).toBe(MISSING);
  });

  it('compacts axis ticks', () => {
    expect(formatCompact(1500)).toBe('1.5K');
    expect(formatCompact(800)).toBe('800');
  });

  it('pluralizes counts', () => {
    expect(pluralize(1, 'event')).toBe('1 event');
    expect(pluralize(1200, 'event')).toBe('1,200 events');
  });
});

describe('formatDuration', () => {
  it.each([
    [0, '0 min'],
    [30, '< 1 min'],
    [45 * 60, '45 min'],
    [3600, '1 h'],
    [12600, '3 h 30 min'],
    [100 * 3600, '100 h'],
  ])('%s seconds → %s', (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });

  it('rejects missing and negative values', () => {
    expect(formatDuration(null)).toBe(MISSING);
    expect(formatDuration(-5)).toBe(MISSING);
  });
});

describe('date formatting', () => {
  it('formats calendar dates without shifting them across timezones', () => {
    // new Date('2026-01-05') would be UTC midnight and render as Jan 4 west of UTC.
    expect(formatDate('2026-01-05')).toBe('Jan 5, 2026');
    expect(formatDate('2026-01-05', { withYear: false })).toBe('Jan 5');
    expect(formatDate('2026-02-30')).toBe(MISSING);
    expect(formatDate(null)).toBe(MISSING);
  });

  it('labels trend buckets by granularity', () => {
    expect(formatPeriod('2026-01-05', 'day')).toBe('Jan 5, 2026');
    expect(formatPeriod('2026-01-05', 'week')).toBe('Week of Jan 5, 2026');
    expect(formatPeriod('2026-01-01', 'month')).toBe('Jan 2026');
  });

  it('describes date ranges, including open ends', () => {
    expect(formatDateRange('', '')).toBe('All dates');
    expect(formatDateRange('2026-01-05', '2026-01-18')).toBe('Jan 5, 2026 – Jan 18, 2026');
    expect(formatDateRange('2026-01-05', '2026-01-05')).toBe('Jan 5, 2026');
    expect(formatDateRange('2026-01-05', '')).toBe('From Jan 5, 2026');
    expect(formatDateRange('', '2026-01-18')).toBe('Up to Jan 18, 2026');
  });

  it('formats instants in local time and handles missing values', () => {
    expect(formatDateTime('2026-01-10T08:00:00Z')).toMatch(/2026/);
    expect(formatDateTime(null)).toBe(MISSING);
    expect(formatDateTime('not a date')).toBe(MISSING);
  });

  it('humanizes enum values', () => {
    expect(humanize('in_progress')).toBe('In progress');
  });
});