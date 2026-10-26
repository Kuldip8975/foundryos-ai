import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App.jsx';
import { SESSION_KEY } from './auth/session.js';
import { jsonResponse, stubFetch } from './test/fetchMock.js';
import { dashboardRoutes } from './test/dashboardRoutes.js';
import { page } from './test/dashboardFixtures.js';
import { SESSION_TOKEN, authError, currentUser, loginResponse, startSession } from './test/authFixtures.js';

const EXTRA = {
  '/health/live': jsonResponse({ status: 'alive', service: 'FoundryOS AI', version: '0.1.0', environment: 'test' }),
  '/health/ready': jsonResponse({ status: 'ready', checks: [] }),
  '/shift-reports': jsonResponse(page([])),
  '/production-records': jsonResponse(page([])),
  '/admin/users': jsonResponse(page([])),
};

function routes(overrides = {}) {
  return dashboardRoutes({ ...EXTRA, ...overrides });
}

function fill(label, value) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function calls(fetchMock, path) {
  return fetchMock.mock.calls.filter(([url]) => new URL(url).pathname.endsWith(path));
}

vi.setConfig({ testTimeout: 20_000 });

beforeEach(() => {
  window.sessionStorage.clear();
});

afterEach(() => {
  window.location.hash = '';
});

describe('sign-in page', () => {
  it('is shown to anyone without a session, and nothing protected is requested', async () => {
    const fetchMock = stubFetch(routes());
    render(<App />);
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: 'About FoundryOS AI' })).toHaveTextContent('AI shift reports');
    expect(screen.queryByRole('link', { name: /sign up|register/i })).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('checks the fields before sending anything', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(routes());
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(screen.getByText('Enter your username or work email.')).toBeInTheDocument();
    expect(screen.getByText('Enter your password.')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('shows the server’s generic failure and clears the password', async () => {
    const user = userEvent.setup();
    stubFetch(
      routes({
        '/auth/login': authError(
          'invalid_credentials',
          'Sign-in failed. Check your username and password. After several failed attempts sign-in is paused for a few minutes.',
        ),
      }),
    );
    render(<App />);
    fill('Username or work email', 'olga');
    fill('Password', 'not-the-password');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Sign-in failed');
    expect(screen.getByLabelText('Password')).toHaveValue('');
    expect(window.sessionStorage.getItem(SESSION_KEY)).toBeNull();
  });

  it('signs an operator in and opens their machines', async () => {
    const user = userEvent.setup();
    const operator = currentUser('operator');
    const fetchMock = stubFetch(routes({ '/auth/login': loginResponse(operator) }));
    render(<App />);
    fill('Username or work email', '  olga ');
    fill('Password', 'Floor-op-5517-violet');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('heading', { level: 2, name: 'My machines' })).toBeInTheDocument();
    expect(window.location.hash).toBe('#/my-work');
    expect(window.sessionStorage.getItem(SESSION_KEY)).toBe(SESSION_TOKEN);
    const [, init] = calls(fetchMock, '/auth/login')[0];
    expect(JSON.parse(init.body)).toEqual({ username: 'olga', password: 'Floor-op-5517-violet' });
    // Later requests carry the session token.
    await waitFor(() => expect(calls(fetchMock, '/downtime-events').length).toBeGreaterThan(0));
    const [, downtime] = calls(fetchMock, '/downtime-events')[0];
    expect(downtime.headers.Authorization).toBe(`Bearer ${SESSION_TOKEN}`);
  });

  it('sends an admin to account administration', async () => {
    const user = userEvent.setup();
    stubFetch(routes({ '/auth/login': loginResponse(currentUser('admin')) }));
    render(<App />);
    fill('Username or work email', 'ada');
    fill('Password', 'Admin-pass-4821-blue');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { level: 2, name: 'Users & access' })).toBeInTheDocument();
    expect(window.location.hash).toBe('#/admin');
  });
});

describe('demo video', () => {
  it('opens from the sign-in page and closes with Escape', async () => {
    const user = userEvent.setup();
    stubFetch(routes());
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'View demo' }));
    const dialog = screen.getByRole('dialog', { name: 'FoundryOS AI walkthrough' });
    const sources = [...dialog.querySelectorAll('source')].map((s) => s.getAttribute('src'));
    expect(sources).toEqual(['/demo/foundryos-demo.mp4', '/demo/foundryos-demo.webm']);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'FoundryOS AI walkthrough' })).not.toBeInTheDocument();
  });
});

describe('temporary passwords', () => {
  it('must be replaced before anything else opens', async () => {
    const user = userEvent.setup();
    startSession();
    const fetchMock = stubFetch(
      routes({
        '/auth/me': jsonResponse(currentUser('supervisor', { must_change_password: true })),
        '/auth/password': jsonResponse(currentUser('supervisor')),
      }),
    );
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Choose your password' })).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument();

    fill('Temporary password', 'Temp-0123456789');
    fill('New password', 'short');
    await user.click(screen.getByRole('button', { name: 'Change password' }));
    expect(screen.getByText('Use at least 12 characters.')).toBeInTheDocument();
    expect(calls(fetchMock, '/auth/password')).toHaveLength(0);

    fill('New password', 'Shift-lead-2026-green');
    fill('Repeat new password', 'Shift-lead-2026-gren');
    await user.click(screen.getByRole('button', { name: 'Change password' }));
    expect(screen.getByText('The passwords do not match.')).toBeInTheDocument();

    fill('Repeat new password', 'Shift-lead-2026-green');
    await user.click(screen.getByRole('button', { name: 'Change password' }));
    expect(await screen.findByRole('heading', { level: 2, name: 'Manufacturing dashboard' })).toBeInTheDocument();
    const [, init] = calls(fetchMock, '/auth/password')[0];
    expect(JSON.parse(init.body)).toEqual({
      current_password: 'Temp-0123456789',
      new_password: 'Shift-lead-2026-green',
    });
  });
});

describe('sessions', () => {
  it('returns to sign-in when a stored session has expired', async () => {
    startSession();
    stubFetch(routes({ '/auth/me': authError('session_expired', 'Your session has expired. Sign in again.') }));
    render(<App />);
    expect(await screen.findByText('Your session expired. Sign in again to continue.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(window.sessionStorage.getItem(SESSION_KEY)).toBeNull();
  });

  it('returns to sign-in when the server ends the session during work', async () => {
    const user = userEvent.setup();
    startSession();
    const table = routes({ '/auth/me': jsonResponse(currentUser('production_manager')) });
    stubFetch(table);
    render(<App />);
    await screen.findByRole('heading', { level: 2, name: 'Manufacturing dashboard' });

    table['/shift-reports'] = authError('session_expired', 'Your session has expired. Sign in again.');
    await user.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'Shift reports' }));
    expect(await screen.findByText('Your session expired. Sign in again to continue.')).toBeInTheDocument();
    expect(window.sessionStorage.getItem(SESSION_KEY)).toBeNull();
  });

  it('signs out on the server and forgets the token', async () => {
    const user = userEvent.setup();
    startSession();
    const fetchMock = stubFetch(
      routes({
        '/auth/me': jsonResponse(currentUser('supervisor')),
        '/auth/logout': { ok: true, status: 204, headers: new Headers(), json: async () => null },
      }),
    );
    render(<App />);
    await screen.findByRole('heading', { level: 2, name: 'Manufacturing dashboard' });
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(await screen.findByText('You signed out.')).toBeInTheDocument();
    expect(calls(fetchMock, '/auth/logout')).toHaveLength(1);
    expect(window.sessionStorage.getItem(SESSION_KEY)).toBeNull();
  });
});