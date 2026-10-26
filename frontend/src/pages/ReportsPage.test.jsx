import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReportsPage } from './ReportsPage.jsx';
import { jsonResponse, requestsTo, stubFetch } from '../test/fetchMock.js';
import { SUMMARY, page } from '../test/dashboardFixtures.js';
import { METRICS, report, summary } from '../test/reportFixtures.js';

function routes(overrides = {}) {
  return {
    '/analytics/dashboard': jsonResponse(SUMMARY),
    '/shift-analysis': jsonResponse(METRICS),
    '/shift-reports': (url, init) =>
      init?.method === 'POST'
        ? jsonResponse(report(5), { status: 201 })
        : jsonResponse(page([summary(report(5)), summary(report(4, { shift: 'B', status: 'failed', content: null }))])),
    '/shift-reports/4': jsonResponse(
      report(4, { status: 'failed', error_code: 'ai_timeout', error_message: 'The AI provider did not respond in time.', content: null }),
    ),
    '/shift-reports/5': jsonResponse(report(5)),
    ...overrides,
  };
}

function bodies(fetchMock) {
  return fetchMock.mock.calls.filter(([, init]) => init?.body).map(([, init]) => JSON.parse(init.body));
}

async function renderPage(overrides) {
  const fetchMock = stubFetch(routes(overrides));
  render(<ReportsPage />);
  // the date defaults to the latest day with data (from the dashboard summary)
  await waitFor(() => expect(screen.getByLabelText('Production date')).toHaveValue('2026-01-07'));
  return fetchMock;
}

function form() {
  return screen.getByRole('form', { name: 'Shift report request' });
}

async function fillShift(user, shift = 'A') {
  await user.type(within(form()).getByLabelText('Shift'), shift);
}

describe('ReportsPage — form', () => {
  it('validates locally before sending anything', async () => {
    const user = userEvent.setup();
    const fetchMock = await renderPage();
    await user.click(screen.getByRole('button', { name: 'Generate AI report' }));
    expect(screen.getByText(/Enter a shift code/)).toBeInTheDocument();
    expect(within(form()).getByLabelText('Shift')).toHaveAttribute('aria-invalid', 'true');

    await fillShift(user);
    fireEvent.change(screen.getByLabelText('Shift start (optional)'), { target: { value: '06:00' } });
    await user.click(screen.getByRole('button', { name: 'Generate AI report' }));
    expect(screen.getByText(/Enter both a start and an end time/)).toBeInTheDocument();
    expect(bodies(fetchMock)).toEqual([]);
  });

  it('previews deterministic metrics without calling the AI', async () => {
    const user = userEvent.setup();
    const fetchMock = await renderPage();
    await fillShift(user);
    await user.click(screen.getByRole('button', { name: 'Preview metrics' }));

    const card = await screen.findByRole('region', { name: 'Measured shift metrics' });
    expect(within(card).getByRole('group', { name: 'Output' })).toHaveTextContent('820');
    expect(within(card).getByRole('group', { name: 'Target achievement' })).toHaveTextContent('86.3%');
    expect(within(card).getByText(/pending inspection/)).toBeInTheDocument();
    expect(Object.fromEntries(requestsTo(fetchMock, '/shift-analysis')[0])).toEqual({
      production_date: '2026-01-07',
      shift: 'A',
    });
    expect(bodies(fetchMock)).toEqual([]);
  });

  it('sends the shift window as UTC instants', async () => {
    const user = userEvent.setup();
    const fetchMock = await renderPage();
    await fillShift(user);
    fireEvent.change(screen.getByLabelText('Shift start (optional)'), { target: { value: '22:00' } });
    fireEvent.change(screen.getByLabelText('Shift end (optional)'), { target: { value: '06:00' } });
    await user.click(screen.getByRole('button', { name: 'Generate AI report' }));
    await screen.findByText(/AI-generated content/);
    expect(bodies(fetchMock)[0]).toEqual({
      production_date: '2026-01-07',
      shift: 'A',
      window_start: new Date(2026, 0, 7, 22).toISOString(),
      window_end: new Date(2026, 0, 8, 6).toISOString(),
      regenerate: false,
    });
  });
});

describe('ReportsPage — generation', () => {
  it('shows progress, then the labelled AI report with its evidence', async () => {
    const user = userEvent.setup();
    let resolve;
    await renderPage({
      '/shift-reports': (url, init) =>
        init?.method === 'POST'
          ? new Promise((r) => {
              resolve = () => r(jsonResponse(report(5), { status: 201 }));
            })
          : jsonResponse(page([])),
    });
    await fillShift(user);
    await user.click(screen.getByRole('button', { name: 'Generate AI report' }));

    expect(await screen.findByText(/Generating the AI report/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Generating…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Preview metrics' })).toBeDisabled();

    resolve();
    const article = await screen.findByRole('article', { name: 'Shift report 5' });
    expect(within(article).getByText(/AI-generated content/)).toBeInTheDocument();
    expect(within(article).getByText(/synthetic demonstration data/)).toBeInTheDocument();
    expect(within(article).getAllByText('Measured fact')).toHaveLength(2);
    expect(within(article).getByText('Possible explanation')).toBeInTheDocument();
    // evidence keys are shown with the measured values they refer to
    const evidence = within(article).getAllByRole('list', { name: 'Evidence' })[0];
    expect(evidence).toHaveTextContent('production.actual_quantity = 820');
    expect(within(article).getByText('Check SYN-CNC-01 tooling.')).toBeInTheDocument();
  });

  it('says when an existing report was reused', async () => {
    const user = userEvent.setup();
    await renderPage({
      '/shift-reports': (url, init) =>
        init?.method === 'POST' ? jsonResponse(report(5), { status: 200 }) : jsonResponse(page([])),
    });
    await fillShift(user);
    await user.click(screen.getByRole('button', { name: 'Generate AI report' }));
    expect(await screen.findByText(/An existing report was returned/)).toBeInTheDocument();
  });

  it('explains a missing AI configuration', async () => {
    const user = userEvent.setup();
    await renderPage({
      '/shift-reports': (url, init) =>
        init?.method === 'POST'
          ? jsonResponse(
              { error: { code: 'ai_not_configured', message: 'AI report generation is not configured on the server.', request_id: 'r1' } },
              { status: 503 },
            )
          : jsonResponse(page([])),
    });
    await fillShift(user);
    await user.click(screen.getByRole('button', { name: 'Generate AI report' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('AI reports are not configured on the server');
    expect(screen.queryByRole('button', { name: /View the saved failed attempt/ })).not.toBeInTheDocument();
  });

  it('reports a duplicate in-progress request', async () => {
    const user = userEvent.setup();
    await renderPage({
      '/shift-reports': (url, init) =>
        init?.method === 'POST'
          ? jsonResponse({ error: { code: 'report_in_progress', message: 'Try again shortly.' } }, { status: 409 })
          : jsonResponse(page([])),
    });
    await fillShift(user);
    await user.click(screen.getByRole('button', { name: 'Generate AI report' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('A report for this shift is already being generated');
  });

  it('links a provider failure to its saved failed attempt', async () => {
    const user = userEvent.setup();
    await renderPage({
      '/shift-reports': (url, init) =>
        init?.method === 'POST'
          ? jsonResponse(
              { error: { code: 'ai_timeout', message: 'The AI provider did not respond in time.', details: [{ report_id: 4 }] } },
              { status: 504 },
            )
          : jsonResponse(page([])),
    });
    await fillShift(user);
    await user.click(screen.getByRole('button', { name: 'Generate AI report' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The AI provider did not respond in time');

    await user.click(screen.getByRole('button', { name: 'View the saved failed attempt (#4)' }));
    const article = await screen.findByRole('article', { name: 'Shift report 4' });
    expect(within(article).getByText('Generation failed.')).toBeInTheDocument();
    expect(within(article).queryByText(/AI-generated content/)).not.toBeInTheDocument();
  });

  it('handles an unreachable API', async () => {
    const user = userEvent.setup();
    await renderPage({ '/shift-analysis': new TypeError('Failed to fetch') });
    await fillShift(user);
    await user.click(screen.getByRole('button', { name: 'Preview metrics' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach the FoundryOS API');
  });
});

describe('ReportsPage — history', () => {
  it('lists saved reports, filters them and opens one', async () => {
    const user = userEvent.setup();
    const fetchMock = await renderPage();
    const history = await screen.findByRole('region', { name: 'Report history' });
    expect(await within(history).findAllByText('Includes synthetic')).toHaveLength(2);
    expect(within(history).getByText('Failed')).toBeInTheDocument();

    const filters = screen.getByRole('group', { name: 'Report history filters' });
    await user.type(within(filters).getByLabelText('Shift'), 'B');
    await user.selectOptions(within(filters).getByLabelText('Status'), 'failed');
    await waitFor(() => {
      const queries = requestsTo(fetchMock, '/shift-reports');
      const last = Object.fromEntries(queries[queries.length - 1]);
      expect(last).toMatchObject({ shift: 'B', status: 'failed' });
    });

    await user.click(within(history).getByRole('button', { name: /View report 4/ }));
    expect(await screen.findByRole('article', { name: 'Shift report 4' })).toHaveTextContent(
      'The AI provider did not respond in time.',
    );
  });

  it('validates the history date range', async () => {
    await renderPage();
    const filters = screen.getByRole('group', { name: 'Report history filters' });
    fireEvent.change(within(filters).getByLabelText('From'), { target: { value: '2026-01-10' } });
    fireEvent.change(within(filters).getByLabelText('To'), { target: { value: '2026-01-01' } });
    expect(await screen.findByRole('alert')).toHaveTextContent('Start date must be on or before the end date.');
    expect(screen.queryByRole('region', { name: 'Report history' })).not.toBeInTheDocument();
  });

  it('shows an empty history', async () => {
    await renderPage({
      '/shift-reports': (url, init) =>
        init?.method === 'POST' ? jsonResponse(report(5), { status: 201 }) : jsonResponse(page([])),
    });
    expect(await screen.findByText('No saved reports match these filters.')).toBeInTheDocument();
  });
});