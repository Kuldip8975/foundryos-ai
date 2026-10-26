import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App.jsx';
import { accountStatus } from './AdminPage.jsx';
import { validateNewUser } from '../api/admin.js';
import { jsonResponse, stubFetch } from '../test/fetchMock.js';
import { MACHINES, page } from '../test/dashboardFixtures.js';
import { currentUser, startSession } from '../test/authFixtures.js';

vi.setConfig({ testTimeout: 20_000 });

function account(id, overrides = {}) {
  return {
    id,
    username: `user${id}`,
    display_name: `User ${id}`,
    email: null,
    role: 'operator',
    is_active: true,
    must_change_password: false,
    locked_until: null,
    last_login_at: '2026-10-15T08:00:00Z',
    password_changed_at: null,
    deactivated_at: null,
    created_at: '2026-10-01T08:00:00Z',
    updated_at: '2026-10-01T08:00:00Z',
    machine_ids: [MACHINES[0].id],
    is_locked: false,
    ...overrides,
  };
}

const ME = account(1, { username: 'ada', display_name: 'Ada Admin', role: 'admin', machine_ids: [] });
const OLGA = account(4, { username: 'olga', display_name: 'Olga Operator' });

function requests(fetchMock, path, method = 'POST') {
  return fetchMock.mock.calls
    .filter(([url, init]) => (init?.method ?? 'GET') === method && new URL(url).pathname.endsWith(path))
    .map(([url, init]) => ({ url: new URL(url), body: init.body ? JSON.parse(init.body) : undefined }));
}

function routes(overrides = {}) {
  return {
    '/auth/me': jsonResponse(currentUser('admin')),
    '/machines': jsonResponse(page(MACHINES, { limit: 200 })),
    '/admin/users': (url, init) =>
      init?.method === 'POST'
        ? jsonResponse(
            { user: account(7, { username: 'otto', display_name: 'Otto Operator', must_change_password: true }), temporary_password: 'Tmp-pass-AbCdEf1234' },
            { status: 201 },
          )
        : jsonResponse(page([ME, OLGA], { limit: 20 })),
    '/admin/users/4/status': jsonResponse({ ...OLGA, is_active: false }),
    '/admin/users/4/reset-password': jsonResponse({ user: { ...OLGA, must_change_password: true }, temporary_password: 'Reset-pass-XyZ98765' }),
    '/admin/audit-events': jsonResponse(
      page([
        { id: 1, event_type: 'login_failed', actor_username: null, target_username: 'olga', target_user_id: 4, success: false, details: { reason: 'wrong_password' }, created_at: '2026-10-15T08:00:00Z' },
      ]),
    ),
    ...overrides,
  };
}

beforeEach(() => {
  window.sessionStorage.clear();
  startSession();
  window.location.hash = '#/admin';
});

afterEach(() => {
  window.location.hash = '';
});

describe('account rules', () => {
  it('summarises account status', () => {
    const now = new Date('2026-10-15T10:00:00Z');
    expect(accountStatus(account(1), now)).toBe('account_active');
    expect(accountStatus(account(1, { is_active: false }), now)).toBe('account_inactive');
    expect(accountStatus(account(1, { locked_until: '2026-10-15T10:05:00Z' }), now)).toBe('account_locked');
    expect(accountStatus(account(1, { locked_until: '2026-10-15T09:00:00Z' }), now)).toBe('account_active');
    expect(accountStatus(account(1, { must_change_password: true }), now)).toBe('account_password_pending');
  });

  it('checks new accounts locally', () => {
    expect(validateNewUser({ username: 'ok.name', displayName: 'Ok', email: '', role: 'operator' })).toEqual({});
    const errors = validateNewUser({ username: 'x', displayName: ' ', email: 'nope', role: 'root' });
    expect(Object.keys(errors).sort()).toEqual(['displayName', 'email', 'role', 'username']);
    const ok = { username: 'raj', displayName: 'Raj', email: '', role: 'operator' };
    expect(validateNewUser({ ...ok, password: 'Plant-floor-2026', repeat: 'Plant-floor-2026' })).toEqual({});
    expect(validateNewUser({ ...ok, password: 'Plant-floor-2026', repeat: 'x' })).toEqual({ repeat: 'The passwords do not match.' });
    expect(validateNewUser({ ...ok, password: 'raj-is-the-best-1' }).password).toMatch(/username/);
  });
});

describe('AdminPage', () => {
  it('lists accounts and protects the admin’s own row', async () => {
    stubFetch(routes());
    render(<App />);
    const table = await screen.findByRole('table', { name: 'Accounts' });
    const rows = within(table).getAllByRole('row');
    expect(rows[1]).toHaveTextContent('Ada Admin');
    expect(rows[1]).toHaveTextContent('This is you');
    expect(rows[2]).toHaveTextContent('Olga Operator');
    expect(rows[2]).toHaveTextContent(MACHINES[0].code);
    expect(within(rows[2]).getByRole('button', { name: 'Deactivate' })).toBeInTheDocument();
  });

  it('creates an account and shows its one-time password once', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(routes());
    render(<App />);
    await screen.findByRole('table', { name: 'Accounts' });
    await user.click(screen.getByRole('button', { name: 'New account' }));
    const form = screen.getByRole('form', { name: 'New account' });
    await user.click(within(form).getByRole('button', { name: 'Create account' }));
    expect(within(form).getByText(/3–50 characters/)).toBeInTheDocument();
    expect(requests(fetchMock, '/admin/users')).toHaveLength(0);

    fireEvent.change(within(form).getByLabelText('Username'), { target: { value: 'otto' } });
    fireEvent.change(within(form).getByLabelText('Full name'), { target: { value: 'Otto Operator' } });
    await user.click(within(form).getByLabelText(new RegExp(MACHINES[1].code)));
    await user.click(within(form).getByRole('button', { name: 'Create account' }));

    const notice = await screen.findByRole('status', { name: 'One-time password' });
    expect(notice).toHaveTextContent('Tmp-pass-AbCdEf1234');
    expect(notice).toHaveTextContent('shown only now');
    const [created] = requests(fetchMock, '/admin/users');
    expect(created.body).toEqual({
      username: 'otto',
      display_name: 'Otto Operator',
      role: 'operator',
      machine_ids: [MACHINES[1].id],
    });
    await user.click(within(notice).getByRole('button', { name: 'Done' }));
    expect(screen.queryByText('Tmp-pass-AbCdEf1234')).not.toBeInTheDocument();
  });

  it('only offers machines for operators', async () => {
    const user = userEvent.setup();
    stubFetch(routes());
    render(<App />);
    await screen.findByRole('table', { name: 'Accounts' });
    await user.click(screen.getByRole('button', { name: 'New account' }));
    const form = screen.getByRole('form', { name: 'New account' });
    expect(within(form).getByRole('group', { name: 'Assigned machines' })).toBeInTheDocument();
    await user.selectOptions(within(form).getByLabelText('Role'), 'supervisor');
    expect(within(form).queryByRole('group', { name: 'Assigned machines' })).not.toBeInTheDocument();
  });

  it('asks before deactivating, then sends the change', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(routes());
    render(<App />);
    const table = await screen.findByRole('table', { name: 'Accounts' });
    const row = within(table).getAllByRole('row')[2];
    await user.click(within(row).getByRole('button', { name: 'Deactivate' }));
    expect(requests(fetchMock, '/admin/users/4/status')).toHaveLength(0);
    expect(within(row).getByRole('group')).toHaveTextContent('They are signed out at once');
    await user.click(within(row).getByRole('button', { name: 'Yes, deactivate' }));
    await waitFor(() => expect(requests(fetchMock, '/admin/users/4/status')).toHaveLength(1));
    expect(requests(fetchMock, '/admin/users/4/status')[0].body).toEqual({ is_active: false });
  });

  it('resets a password and shows the new one-time password', async () => {
    const user = userEvent.setup();
    stubFetch(routes());
    render(<App />);
    const table = await screen.findByRole('table', { name: 'Accounts' });
    const row = within(table).getAllByRole('row')[2];
    await user.click(within(row).getByRole('button', { name: 'Reset password' }));
    const form = screen.getByRole('form', { name: 'Reset password for olga' });
    await user.click(within(form).getByRole('button', { name: 'Reset password' }));
    expect(await screen.findByRole('status', { name: 'One-time password' })).toHaveTextContent('Reset-pass-XyZ98765');
  });

  it('resets to a password the admin chooses, without forcing a change', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(
      routes({
        '/admin/users/4/reset-password': jsonResponse({ user: OLGA, temporary_password: null }),
      }),
    );
    render(<App />);
    const table = await screen.findByRole('table', { name: 'Accounts' });
    await user.click(within(within(table).getAllByRole('row')[2]).getByRole('button', { name: 'Reset password' }));
    const form = screen.getByRole('form', { name: 'Reset password for olga' });
    fireEvent.change(within(form).getByLabelText('Password (optional)'), { target: { value: 'Floor-easy-2026' } });
    fireEvent.change(within(form).getByLabelText('Repeat password'), { target: { value: 'Floor-easy-2026' } });
    await user.click(within(form).getByLabelText(/choose their own password/));
    await user.click(within(form).getByRole('button', { name: 'Reset password' }));
    expect(await screen.findByText(/Password set for olga/)).toBeInTheDocument();
    expect(requests(fetchMock, '/admin/users/4/reset-password')[0].body).toEqual({
      new_password: 'Floor-easy-2026',
      require_password_change: false,
    });
    expect(screen.queryByRole('status', { name: 'One-time password' })).not.toBeInTheDocument();
  });

  it('creates an account with a password the admin chooses', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(
      routes({
        '/admin/users': (url, init) =>
          init?.method === 'POST'
            ? jsonResponse({ user: account(8, { username: 'raj', display_name: 'Raj Patil' }), temporary_password: null }, { status: 201 })
            : jsonResponse(page([ME, OLGA], { limit: 20 })),
      }),
    );
    render(<App />);
    await screen.findByRole('table', { name: 'Accounts' });
    await user.click(screen.getByRole('button', { name: 'New account' }));
    const form = screen.getByRole('form', { name: 'New account' });
    fireEvent.change(within(form).getByLabelText('Username'), { target: { value: 'raj' } });
    fireEvent.change(within(form).getByLabelText('Full name'), { target: { value: 'Raj Patil' } });
    fireEvent.change(within(form).getByLabelText('Password (optional)'), { target: { value: 'short' } });
    await user.click(within(form).getByRole('button', { name: 'Create account' }));
    expect(within(form).getByText('Use at least 12 characters.')).toBeInTheDocument();

    fireEvent.change(within(form).getByLabelText('Password (optional)'), { target: { value: 'Plant-floor-2026' } });
    fireEvent.change(within(form).getByLabelText('Repeat password'), { target: { value: 'Plant-floor-2026' } });
    await user.click(within(form).getByLabelText(/choose their own password/));
    await user.click(within(form).getByRole('button', { name: 'Create account' }));
    expect(await screen.findByText(/Password set for raj/)).toBeInTheDocument();
    expect(requests(fetchMock, '/admin/users')[0].body).toMatchObject({
      username: 'raj',
      temporary_password: 'Plant-floor-2026',
      require_password_change: false,
    });
  });

  it('shows server refusals such as the last-admin rule', async () => {
    const user = userEvent.setup();
    stubFetch(
      routes({
        '/admin/users/4/status': jsonResponse(
          { error: { code: 'last_admin', message: 'This is the last active admin and cannot be deactivated.', request_id: 'r' } },
          { status: 409 },
        ),
      }),
    );
    render(<App />);
    const table = await screen.findByRole('table', { name: 'Accounts' });
    const row = within(table).getAllByRole('row')[2];
    await user.click(within(row).getByRole('button', { name: 'Deactivate' }));
    await user.click(within(row).getByRole('button', { name: 'Yes, deactivate' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('At least one active admin is required');
  });

  it('shows the access log with outcome filters', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(routes());
    render(<App />);
    await screen.findByRole('table', { name: 'Accounts' });
    await user.click(screen.getByRole('tab', { name: 'Access log' }));
    const log = await screen.findByRole('table', { name: 'Access log' });
    expect(log).toHaveTextContent('Login failed');
    expect(log).toHaveTextContent('Reason: wrong_password');
    await user.selectOptions(screen.getByLabelText('Outcome'), 'false');
    await waitFor(() =>
      expect(requests(fetchMock, '/admin/audit-events', 'GET').at(-1).url.searchParams.get('success')).toBe('false'),
    );
  });
});