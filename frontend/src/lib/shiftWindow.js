/**
 * Shift time window from a calendar date and local clock times.
 *
 * Times are entered in the browser's local time zone and sent as explicit
 * UTC instants. An end time at or before the start time means the shift ends
 * on the next day (e.g. 22:00 → 06:00).
 */

import { parseISODate } from './dates.js';

const TIME = /^([01]\d|2[0-3]):([0-5]\d)$/;

function at(isoDate, time, dayOffset = 0) {
  const date = parseISODate(isoDate);
  const [, hh, mm] = TIME.exec(time);
  date.setDate(date.getDate() + dayOffset);
  date.setHours(Number(hh), Number(mm), 0, 0);
  return date;
}

/**
 * @returns {{ window: null | {window_start: string, window_end: string}, error: string | null }}
 *   window is null when no times were entered (downtime will not be calculated).
 */
export function buildShiftWindow(productionDate, startTime, endTime) {
  if (!startTime && !endTime) return { window: null, error: null };
  if (!startTime || !endTime) {
    return { window: null, error: 'Enter both a start and an end time, or leave both empty.' };
  }
  if (!parseISODate(productionDate)) {
    return { window: null, error: 'Choose a valid production date first.' };
  }
  if (!TIME.test(startTime) || !TIME.test(endTime)) {
    return { window: null, error: 'Times must be in HH:MM format.' };
  }
  const start = at(productionDate, startTime);
  const end = at(productionDate, endTime, endTime <= startTime ? 1 : 0);
  return { window: { window_start: start.toISOString(), window_end: end.toISOString() }, error: null };
}