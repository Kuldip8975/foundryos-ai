/**
 * Calendar-date helpers.
 *
 * Production data is keyed by the plant's calendar date ("YYYY-MM-DD"), which
 * is NOT an instant. These helpers never pass such strings to `new Date(str)`
 * (that would parse them as UTC midnight and show the previous day west of
 * UTC). Instants sent to the API are built from local midnight and serialised
 * with toISOString(), so they always carry an explicit UTC offset.
 */

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Parse "YYYY-MM-DD" into a local Date at midnight, or null if invalid. */
export function parseISODate(value) {
  const match = ISO_DATE.exec(value ?? '');
  if (!match) return null;
  const [year, month, day] = match.slice(1).map(Number);
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
    return null; // e.g. 2026-02-30
  }
  return date;
}

/** Local calendar date of a Date as "YYYY-MM-DD". */
export function toISODate(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

export function addDays(isoDate, days) {
  const date = parseISODate(isoDate);
  if (!date) return null;
  date.setDate(date.getDate() + days);
  return toISODate(date);
}

export const DATE_PRESETS = [
  { value: 'all', label: 'All dates' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: '90d', label: 'Last 90 days' },
  { value: 'custom', label: 'Custom range' },
];

const PRESET_DAYS = { '7d': 7, '30d': 30, '90d': 90 };

/**
 * Date range for a preset, inclusive, relative to `today` (local calendar).
 * 'all' → no bounds; 'custom' → null (the caller keeps the user's dates).
 */
export function presetRange(preset, today = new Date()) {
  if (preset === 'all') return { from: '', to: '' };
  const days = PRESET_DAYS[preset];
  if (!days) return null;
  const to = toISODate(today);
  return { from: addDays(to, -(days - 1)), to };
}

/**
 * Validate a user-entered range. Returns an error message or null.
 * Empty bounds are allowed (open-ended range).
 */
export function validateDateRange(from, to) {
  if (from && !parseISODate(from)) return 'Start date is not a valid date.';
  if (to && !parseISODate(to)) return 'End date is not a valid date.';
  if (from && to && from > to) return 'Start date must be on or before the end date.';
  return null;
}

/**
 * The browser's UTC offset in minutes (e.g. 330 for UTC+05:30) on a given
 * calendar date — the backend uses it to turn plant dates into a UTC window.
 */
export function utcOffsetMinutes(isoDate) {
  const date = parseISODate(isoDate) ?? new Date();
  return -date.getTimezoneOffset();
}

export function formatUtcOffset(minutes) {
  const sign = minutes < 0 ? '-' : '+';
  const abs = Math.abs(minutes);
  const hh = String(Math.floor(abs / 60)).padStart(2, '0');
  const mm = String(abs % 60).padStart(2, '0');
  return `UTC${sign}${hh}:${mm}`;
}

/** First instant of a local calendar day, as an ISO-8601 UTC string. */
export function localDayStartISO(isoDate) {
  const date = parseISODate(isoDate);
  return date ? date.toISOString() : null;
}

/** Last millisecond of a local calendar day, as an ISO-8601 UTC string. */
export function localDayEndISO(isoDate) {
  const date = parseISODate(isoDate);
  if (!date) return null;
  date.setDate(date.getDate() + 1);
  return new Date(date.getTime() - 1).toISOString();
}