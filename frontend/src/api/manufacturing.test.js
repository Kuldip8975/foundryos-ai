import { describe, expect, it } from 'vitest';
import { buildQuery } from './query.js';
import {
  MAX_PAGE_SIZE,
  dashboardParams,
  fetchAllPages,
  fetchDashboardSummary,
  fetchDowntimeEvents,
} from './manufacturing.js';
import { jsonResponse, requestsTo, stubFetch } from '../test/fetchMock.js';
import { SUMMARY, page } from '../test/dashboardFixtures.js';

describe('buildQuery', () => {
  it('omits unset values and keeps order', () => {
    expect(buildQuery({ a: 1, b: '', c: null, d: undefined, e: false, f: 'x y' })).toBe('?a=1&e=false&f=x+y');
    expect(buildQuery({})).toBe('');
  });
});

describe('dashboardParams', () => {
  it('maps UI filters to API parameter names and types', () => {
    const params = dashboardParams(
      { dateFrom: '2026-01-05', dateTo: '2026-01-18', shift: 'A', machineId: '3', productId: '', dataSource: 'manual' },
      330,
    );
    expect(params).toEqual({
      date_from: '2026-01-05',
      date_to: '2026-01-18',
      shift: 'A',
      machine_id: 3,
      product_id: null,
      data_source: 'manual',
      utc_offset_minutes: 330,
    });
  });
});

describe('manufacturing API', () => {
  it('requests the dashboard summary with only the filters that are set', async () => {
    const fetchMock = stubFetch({ '/analytics/dashboard': jsonResponse(SUMMARY) });
    await expect(
      fetchDashboardSummary(dashboardParams({ machineId: '2' }, -300)),
    ).resolves.toEqual(SUMMARY);
    const [query] = requestsTo(fetchMock, '/analytics/dashboard');
    expect(Object.fromEntries(query)).toEqual({ machine_id: '2', utc_offset_minutes: '-300' });
  });

  it('follows `total` across pages for reference lists', async () => {
    const rows = Array.from({ length: 450 }, (_, i) => ({ id: i + 1 }));
    const fetchMock = stubFetch({
      '/machines': (url) => {
        const offset = Number(url.searchParams.get('offset'));
        const limit = Number(url.searchParams.get('limit'));
        return jsonResponse(page(rows.slice(offset, offset + limit), { total: rows.length, limit, offset }));
      },
    });
    const items = await fetchAllPages('/machines');
    expect(items).toHaveLength(450);
    const offsets = requestsTo(fetchMock, '/machines').map((q) => q.get('offset'));
    expect(offsets).toEqual(['0', '200', '400']);
    expect(requestsTo(fetchMock, '/machines')[0].get('limit')).toBe(String(MAX_PAGE_SIZE));
  });

  it('stops paging when the server returns an empty page', async () => {
    const fetchMock = stubFetch({ '/machines': jsonResponse(page([], { total: 5 })) });
    await expect(fetchAllPages('/machines')).resolves.toEqual([]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('rejects responses that are not a pagination envelope', async () => {
    stubFetch({ '/downtime-events': jsonResponse([{ id: 1 }]) });
    await expect(fetchDowntimeEvents({})).rejects.toMatchObject({ kind: 'parse' });
  });

  it('surfaces the backend error envelope', async () => {
    stubFetch({
      '/analytics/dashboard': jsonResponse(
        { error: { code: 'invalid_date_range', message: 'date_from must be on or before date_to', request_id: 'r1' } },
        { status: 422 },
      ),
    });
    await expect(fetchDashboardSummary({})).rejects.toMatchObject({
      kind: 'http',
      status: 422,
      code: 'invalid_date_range',
      requestId: 'r1',
    });
  });
});