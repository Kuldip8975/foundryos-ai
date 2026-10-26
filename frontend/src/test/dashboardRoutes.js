import { jsonResponse } from './fetchMock.js';
import {
  MACHINES,
  PRODUCTS,
  SUMMARY,
  downtimeEvent,
  maintenanceRequest,
  page,
} from './dashboardFixtures.js';

/** 14 downtime events, served 10 per page according to limit/offset. */
export function pagedDowntime(url) {
  const limit = Number(url.searchParams.get('limit') ?? 50);
  const offset = Number(url.searchParams.get('offset') ?? 0);
  const all = Array.from({ length: 14 }, (_, i) => downtimeEvent(i + 1));
  return jsonResponse(page(all.slice(offset, offset + limit), { total: all.length, limit, offset }));
}

/** Route table for every endpoint the dashboard calls; override per test. */
export function dashboardRoutes(overrides = {}) {
  return {
    '/analytics/dashboard': jsonResponse(SUMMARY),
    '/machines': jsonResponse(page(MACHINES, { limit: 200 })),
    '/products': jsonResponse(page(PRODUCTS, { limit: 200 })),
    '/downtime-events': pagedDowntime,
    '/maintenance-requests': jsonResponse(
      page([maintenanceRequest(1), maintenanceRequest(2, { status: 'in_progress', priority: 'critical' })]),
    ),
    ...overrides,
  };
}