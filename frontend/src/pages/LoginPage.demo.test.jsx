import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App.jsx';
import { jsonResponse, stubFetch } from '../test/fetchMock.js';
import { dashboardRoutes } from '../test/dashboardRoutes.js';
import { currentUser, loginResponse } from '../test/authFixtures.js';

// A public demo build sets VITE_DEMO_PASSWORD; simulate that build here.
vi.mock('../config/env.js', () => ({
  config: Object.freeze({
    apiBaseUrl: 'http://api.test/api/v1',
    configError: null,
    mode: 'test',
    requestTimeoutMs: 8000,
    demoPassword: 'Public-demo-2026',
  }),
  parseApiBaseUrl: () => ({ apiBaseUrl: 'http://api.test/api/v1', error: null }),
}));

beforeEach(() => {
  window.sessionStorage.clear();
  window.location.hash = '';
});

describe('public demo sign-in', () => {
  it('signs in with a demo role in one click', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(
      dashboardRoutes({
        '/auth/login': loginResponse(currentUser('supervisor', { username: 'demo.supervisor' })),
        '/health/live': jsonResponse({ status: 'alive', service: 'FoundryOS AI', version: '0.1.0', environment: 'test' }),
        '/health/ready': jsonResponse({ status: 'ready', checks: [] }),
      }),
    );
    render(<App />);
    expect(screen.getByRole('heading', { name: 'Try the live demo' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Supervisor' }));
    expect(await screen.findByRole('heading', { level: 2, name: 'Manufacturing dashboard' })).toBeInTheDocument();
    const [, init] = fetchMock.mock.calls.find(([url]) => new URL(url).pathname.endsWith('/auth/login'));
    expect(JSON.parse(init.body)).toEqual({ username: 'demo.supervisor', password: 'Public-demo-2026' });
  });
});
