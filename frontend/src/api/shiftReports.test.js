import { describe, expect, it } from 'vitest';
import {
  createShiftReport,
  fetchShiftAnalysis,
  fetchShiftReport,
  fetchShiftReports,
  shiftScopeParams,
} from './shiftReports.js';
import { jsonResponse, requestsTo, stubFetch } from '../test/fetchMock.js';
import { METRICS, report, summary } from '../test/reportFixtures.js';
import { page } from '../test/dashboardFixtures.js';

const SCOPE = { productionDate: '2026-01-10', shift: 'A', window: null, dataSource: '' };

describe('shift report API', () => {
  it('maps the form scope to API fields', () => {
    expect(shiftScopeParams({ ...SCOPE, window: { window_start: 's', window_end: 'e' }, dataSource: 'manual' })).toEqual({
      production_date: '2026-01-10', shift: 'A', window_start: 's', window_end: 'e', data_source: 'manual',
    });
  });

  it('requests a shift analysis with query parameters', async () => {
    const fetchMock = stubFetch({ '/shift-analysis': jsonResponse(METRICS) });
    await expect(fetchShiftAnalysis(shiftScopeParams(SCOPE))).resolves.toEqual(METRICS);
    expect(Object.fromEntries(requestsTo(fetchMock, '/shift-analysis')[0])).toEqual({
      production_date: '2026-01-10',
      shift: 'A',
    });
  });

  it('POSTs a JSON body without unset fields and reports reuse', async () => {
    const fetchMock = stubFetch({ '/shift-reports': jsonResponse(report(3), { status: 201 }) });
    const created = await createShiftReport(shiftScopeParams(SCOPE), { regenerate: true });
    expect(created).toEqual({ report: report(3), reused: false });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe('POST');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(init.body)).toEqual({ production_date: '2026-01-10', shift: 'A', regenerate: true });

    stubFetch({ '/shift-reports': jsonResponse(report(3), { status: 200 }) });
    expect((await createShiftReport(shiftScopeParams(SCOPE))).reused).toBe(true);
  });

  it('keeps error details such as the failed report id', async () => {
    stubFetch({
      '/shift-reports': jsonResponse(
        { error: { code: 'ai_timeout', message: 'The AI provider did not respond in time.', details: [{ report_id: 9 }], request_id: 'r9' } },
        { status: 504 },
      ),
    });
    await expect(createShiftReport(shiftScopeParams(SCOPE))).rejects.toMatchObject({
      kind: 'http', status: 504, code: 'ai_timeout', details: [{ report_id: 9 }],
    });
  });

  it('lists and fetches saved reports', async () => {
    const fetchMock = stubFetch({
      '/shift-reports': jsonResponse(page([summary(report(1))], { total: 1 })),
      '/shift-reports/1': jsonResponse(report(1)),
    });
    const list = await fetchShiftReports({ shift: 'A', status: null, limit: 10, offset: 0 });
    expect(list.total).toBe(1);
    expect(Object.fromEntries(requestsTo(fetchMock, '/shift-reports')[0])).toEqual({ shift: 'A', limit: '10', offset: '0' });
    await expect(fetchShiftReport(1)).resolves.toEqual(report(1));
  });
});