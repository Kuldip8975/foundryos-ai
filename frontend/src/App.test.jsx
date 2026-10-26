import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App.jsx';
import { jsonResponse, stubFetch } from './test/fetchMock.js';
import { dashboardRoutes } from './test/dashboardRoutes.js';
import { emptySummary } from './test/dashboardFixtures.js';
import { currentUser, startSession } from './test/authFixtures.js';

const LIVE = { status: 'alive', service: 'FoundryOS AI', version: '0.1.0', environment: 'development' };

const READY = {
  status: 'ready',
  checks: [
    { name: 'database', status: 'pass', latency_ms: 1.2 },
    { name: 'migrations', status: 'pass', latency_ms: 0.4, detail: "At head ['0001_baseline']" },
  ],
};

const NOT_READY = {
  status: 'not_ready',
  checks: [
    { name: 'database', status: 'fail', latency_ms: 5, detail: 'Database is unreachable or rejected the connection' },
    { name: 'migrations', status: 'skip', detail: 'Skipped: database unavailable' },
  ],
};

const ME = { '/auth/me': jsonResponse(currentUser('supervisor')) };

beforeEach(() => {
  window.sessionStorage.clear();
  startSession(); // signed in earlier in this tab, as a supervisor
});

afterEach(() => {
  window.location.hash = '';
});

async function renderApp() {
  render(<App />);
  await screen.findByRole('heading', { level: 2, name: 'Manufacturing dashboard' });
}

function statusPanel() {
  return screen.getByRole('region', { name: /backend connectivity/i });
}

describe('App shell', () => {
  it('identifies the product and shows the empty state without fake data', async () => {
    stubFetch(
      dashboardRoutes({
        ...ME,
        '/analytics/dashboard': jsonResponse(emptySummary()),
        '/health/live': jsonResponse(LIVE),
        '/health/ready': jsonResponse(READY),
      }),
    );
    await renderApp();
    expect(screen.getByRole('heading', { level: 1, name: 'FoundryOS AI' })).toBeInTheDocument();
    expect(
      await screen.findByRole('region', { name: /no manufacturing data for these filters/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Total output' })).not.toBeInTheDocument();
    await screen.findByText('Connected');
  });

  it('shows connected status with live checks', async () => {
    stubFetch(dashboardRoutes({ ...ME, '/health/live': jsonResponse(LIVE), '/health/ready': jsonResponse(READY) }));
    await renderApp();

    expect(await within(statusPanel()).findByText('Connected')).toBeInTheDocument();
    expect(within(statusPanel()).getByText('PostgreSQL database')).toBeInTheDocument();
    expect(within(statusPanel()).getByText('1.2 ms')).toBeInTheDocument();
  });

  it('shows a degraded state when readiness returns 503', async () => {
    stubFetch(
      dashboardRoutes({
        ...ME,
        '/health/live': jsonResponse(LIVE),
        '/health/ready': jsonResponse(NOT_READY, { status: 503 }),
      }),
    );
    await renderApp();
    expect(await within(statusPanel()).findByText('Degraded')).toBeInTheDocument();
    expect(within(statusPanel()).getByRole('alert')).toHaveTextContent(/not ready/i);
    expect(within(statusPanel()).getByText(/unreachable or rejected/i)).toBeInTheDocument();
  });

  it('shows an error state when the API is unreachable and recovers on retry', async () => {
    const routes = dashboardRoutes({
      ...ME,
      '/health/live': new TypeError('Failed to fetch'),
      '/health/ready': jsonResponse(READY),
    });
    stubFetch(routes);
    await renderApp();

    expect(await within(statusPanel()).findByText('Offline')).toBeInTheDocument();
    expect(within(statusPanel()).getByRole('alert')).toHaveTextContent(/cannot reach the api/i);

    routes['/health/live'] = jsonResponse(LIVE);
    await userEvent.click(within(statusPanel()).getByRole('button', { name: /re-check/i }));
    expect(await within(statusPanel()).findByText('Connected')).toBeInTheDocument();
  });
});