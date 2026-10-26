/**
 * Manufacturing data and analytics endpoints (Modules 1–2).
 *
 * Paths and response shapes mirror the FastAPI implementation:
 *   GET /analytics/dashboard        → DashboardSummary
 *   GET /machines, /products,
 *       /downtime-events,
 *       /maintenance-requests       → { items, total, limit, offset }
 */

import { ApiError, getJson } from './client.js';

/** Largest page the backend accepts (app/api/deps.py MAX_PAGE_SIZE). */
export const MAX_PAGE_SIZE = 200;
/** Safety cap for fetchAllPages: 50 × 200 = 10,000 rows. */
export const MAX_PAGES = 50;

/**
 * Dashboard filters → API query parameters. Empty filters are omitted by the
 * client; ids are sent as numbers.
 */
export function dashboardParams(filters, utcOffsetMinutes) {
  return {
    date_from: filters.dateFrom || null,
    date_to: filters.dateTo || null,
    shift: filters.shift || null,
    machine_id: filters.machineId ? Number(filters.machineId) : null,
    product_id: filters.productId ? Number(filters.productId) : null,
    data_source: filters.dataSource || null,
    utc_offset_minutes: utcOffsetMinutes,
  };
}

export function fetchDashboardSummary(params, options = {}) {
  return getJson('/analytics/dashboard', { ...options, params });
}

function assertPage(body, path) {
  if (!body || !Array.isArray(body.items) || typeof body.total !== 'number') {
    throw new ApiError(`Unexpected response from ${path}.`, { kind: 'parse' });
  }
  return body;
}

/** One page of a list endpoint; validates the pagination envelope. */
export async function fetchPage(path, params = {}, options = {}) {
  return assertPage(await getJson(path, { ...options, params }), path);
}

/**
 * Every row of a list endpoint, following `total` page by page. Used for small
 * reference lists (machines, products) that populate filter options.
 */
export async function fetchAllPages(path, params = {}, options = {}) {
  const items = [];
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const body = await fetchPage(
      path,
      { ...params, limit: MAX_PAGE_SIZE, offset: page * MAX_PAGE_SIZE },
      options,
    );
    items.push(...body.items);
    if (body.items.length === 0 || items.length >= body.total) break;
  }
  return items;
}

export function fetchMachines(options) {
  return fetchAllPages('/machines', {}, options);
}

export function fetchProducts(options) {
  return fetchAllPages('/products', {}, options);
}

export function fetchDowntimeEvents(params, options) {
  return fetchPage('/downtime-events', params, options);
}

export function fetchMaintenanceRequests(params, options) {
  return fetchPage('/maintenance-requests', params, options);
}