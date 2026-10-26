/**
 * Shift analysis and AI shift report endpoints (Module 3).
 *
 *   GET  /shift-analysis            → ShiftMetrics (deterministic, no AI)
 *   POST /shift-reports             → ShiftReportRead (201 new, 200 reused)
 *   GET  /shift-reports             → { items: ShiftReportSummary[], total, limit, offset }
 *   GET  /shift-reports/{id}        → ShiftReportRead
 */

import { getJson, sendJson } from './client.js';
import { fetchPage } from './manufacturing.js';

/**
 * AI generation can take far longer than an ordinary request. The server gives
 * up after at most AI_REQUEST_TIMEOUT_SECONDS (max 120) plus a short retry, so
 * the browser waits longer than that and always receives the server's answer.
 */
export const GENERATION_TIMEOUT_MS = 180_000;

/** Form scope → API fields; unset optional values are omitted. */
export function shiftScopeParams({ productionDate, shift, window, dataSource }) {
  return {
    production_date: productionDate,
    shift,
    window_start: window?.window_start ?? null,
    window_end: window?.window_end ?? null,
    data_source: dataSource || null,
  };
}

export function fetchShiftAnalysis(params, options = {}) {
  return getJson('/shift-analysis', { ...options, params });
}

/** Resolves with { report, reused } — reused is true when the server returned an existing report. */
export async function createShiftReport(params, { regenerate = false, ...options } = {}) {
  const body = Object.fromEntries(Object.entries(params).filter(([, value]) => value !== null));
  const { status, data } = await sendJson('/shift-reports', {
    ...options,
    body: { ...body, regenerate },
    timeoutMs: GENERATION_TIMEOUT_MS,
  });
  return { report: data, reused: status === 200 };
}

export function fetchShiftReports(params, options) {
  return fetchPage('/shift-reports', params, options);
}

export function fetchShiftReport(id, options) {
  return getJson(`/shift-reports/${encodeURIComponent(id)}`, options);
}