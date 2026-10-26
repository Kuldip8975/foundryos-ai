/**
 * Display formatting. Missing values render as an em dash, never as 0, so
 * "no data" is never mistaken for "zero".
 *
 * A fixed locale keeps output identical across browsers and test runs.
 */

import { parseISODate } from './dates.js';

export const LOCALE = 'en-US';
export const MISSING = '—';

const integer = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 });
const compact = new Intl.NumberFormat(LOCALE, { notation: 'compact', maximumFractionDigits: 1 });

function isNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

export function formatNumber(value) {
  return isNumber(value) ? integer.format(value) : MISSING;
}

/** 1,284 → "1.3K"; used for axis ticks. */
export function formatCompact(value) {
  return isNumber(value) ? compact.format(value) : MISSING;
}

/** Ratio (0.123) → "12.3%". */
export function formatPercent(ratio, digits = 1) {
  if (!isNumber(ratio)) return MISSING;
  return `${(ratio * 100).toFixed(digits)}%`;
}

/** Seconds → "3 h 25 min", "45 min", "< 1 min", "0 min". */
export function formatDuration(seconds) {
  if (!isNumber(seconds) || seconds < 0) return MISSING;
  if (seconds === 0) return '0 min';
  if (seconds < 60) return '< 1 min';
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return `${minutes} min`;
  if (minutes === 0) return `${integer.format(hours)} h`;
  return `${integer.format(hours)} h ${minutes} min`;
}

/** Seconds → hours with one decimal, for chart axes. */
export function secondsToHours(seconds) {
  return isNumber(seconds) ? seconds / 3600 : null;
}

/** "2026-01-05" → "Jan 5, 2026" (calendar date; no timezone shift). */
export function formatDate(isoDate, { withYear = true } = {}) {
  const date = parseISODate(isoDate);
  if (!date) return MISSING;
  return date.toLocaleDateString(LOCALE, {
    month: 'short',
    day: 'numeric',
    ...(withYear ? { year: 'numeric' } : {}),
  });
}

/** "2026-01" style label for monthly buckets: "Jan 2026". */
export function formatMonth(isoDate) {
  const date = parseISODate(isoDate);
  return date ? date.toLocaleDateString(LOCALE, { month: 'short', year: 'numeric' }) : MISSING;
}

/** Label for a trend bucket start date. */
export function formatPeriod(isoDate, granularity) {
  if (granularity === 'month') return formatMonth(isoDate);
  if (granularity === 'week') return `Week of ${formatDate(isoDate)}`;
  return formatDate(isoDate);
}

/** ISO instant → local date and time, e.g. "Jan 10, 2026, 2:30 PM". */
export function formatDateTime(isoInstant) {
  if (!isoInstant) return MISSING;
  const date = new Date(isoInstant);
  if (Number.isNaN(date.getTime())) return MISSING;
  return date.toLocaleString(LOCALE, { dateStyle: 'medium', timeStyle: 'short' });
}

/** "2026-01-05".."2026-01-18" → "Jan 5, 2026 – Jan 18, 2026"; open ends allowed. */
export function formatDateRange(from, to) {
  if (!from && !to) return 'All dates';
  if (from && !to) return `From ${formatDate(from)}`;
  if (!from && to) return `Up to ${formatDate(to)}`;
  if (from === to) return formatDate(from);
  return `${formatDate(from)} – ${formatDate(to)}`;
}

/** 1 → "1 event", 3 → "3 events" (formatted count). */
export function pluralize(count, singular, plural = `${singular}s`) {
  return `${formatNumber(count)} ${count === 1 ? singular : plural}`;
}

export function humanize(value) {
  if (!value) return MISSING;
  const text = String(value).replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}