import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App.jsx';
import { localInputToISO, validateDowntime, validateOutput } from './MyWorkPage.jsx';
import { jsonResponse, stubFetch } from '../test/fetchMock.js';
import { dashboardRoutes } from '../test/dashboardRoutes.js';
import { downtimeEvent, page } from '../test/dashboardFixtures.js';
import { currentUser, startSession } from '../test/authFixtures.js';

vi.setConfig({ testTimeout: 20_000 });

beforeEach(() => {
  window.sessionStorage.clear();
  startSession();
});

afterEach(() => {
  window.location.hash = '';
});

function posts(fetchMock, path) {
  return fetchMock.mock.calls
    .filter(([url, init]) => init?.method === 'POST' && new URL(url).pathname.endsWith(path))
    .map(([, init]) => JSON.parse(init.body));
}

describe('operator form rules', () => {
  const now = new Date('2026-10-15T10:00:00Z');

  it('checks a downtime report like the server does', () => {
    expect(validateDowntime({ machineId: '', startedAt: '', endedAt: '', reason: '' }, now)).toEqual({
      machineId: 'Choose a machine.',
      startedAt: 'Enter when the machine stopped.',
      reason: 'Describe why the machine stopped.',
    });
    const ok = { machineId: '1', startedAt: '2026-10-15T08:00', endedAt: '', reason: 'Jam' };
    expect(validateDowntime(ok, now)).toEqual({});
    expect(validateDowntime({ ...ok, endedAt: '2026-10-15T07:00' }, now).endedAt).toMatch(/restart after/);
    expect(validateDowntime({ ...ok, startedAt: '2027-01-01T08:00' }, now).startedAt).toMatch(/future/);
    expect(validateDowntime({ ...ok, reason: 'x'.repeat(501) }, now).reason).toMatch(/under 500/);
    // Works in every time zone (e.g. India is UTC+05:30, so minutes change too).
    expect(localInputToISO('2026-10-15T08:00')).toBe(new Date(2026, 9, 15, 8, 0).toISOString());
    expect(localInputToISO('')).toBeNull();
  });

  it('checks shift output quantities', () => {
    const ok = {
      machineId: '1', productId: '2', productionDate: '2026-10-14', shift: 'A',
      target: '100', actual: '90', accepted: '85', rejected: '5',
    };
    expect(validateOutput(ok, '2026-10-15')).toEqual({});
    expect(validateOutput({ ...ok, accepted: '86' }, '2026-10-15').accepted).toMatch(/cannot exceed/);
    expect(validateOutput({ ...ok, rejected: '-1' }, '2026-10-15').rejected).toMatch(/Whole number/);
    expect(validateOutput({ ...ok, target: '1.5' }, '2026-10-15').target).toMatch(/Whole number/);
    expect(validateOutput({ ...ok, productionDate: '2026-10-16' }, '2026-10-15').productionDate).toMatch(/future/);
    expect(validateOutput({ ...ok, shift: 'A B' }, '2026-10-15').shift).toMatch(/shift code/);
  });
});

describe('MyWorkPage', () => {
  function routes(overrides = {}) {
    return dashboardRoutes({
      '/auth/me': jsonResponse(currentUser('operator')),
      '/production-records': (url, init) =>
        init?.method === 'POST' ? jsonResponse({ id: 9 }, { status: 201 }) : jsonResponse(page([])),
      '/downtime-events': (url, init) =>
        init?.method === 'POST'
          ? jsonResponse(downtimeEvent(99, { machine_id: 1, status: 'ongoing', ended_at: null }), { status: 201 })
          : jsonResponse(page([downtimeEvent(1, { machine_id: 1, status: 'ongoing', ended_at: null, reason: 'Spindle jam' })])),
      ...overrides,
    });
  }

  it('shows the assigned machines and what is down right now', async () => {
    stubFetch(routes());
    render(<App />);
    const machines = await screen.findByRole('list', { name: 'Your machines' });
    expect(machines).toHaveTextContent('CNC-01');
    expect(await within(machines).findByText(/Spindle jam/)).toBeInTheDocument();
    expect(screen.getByText(/You record data for CNC-01/)).toBeInTheDocument();
  });

  it('records downtime for an assigned machine', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(routes());
    render(<App />);
    const form = await screen.findByRole('form', { name: 'Report downtime' });
    expect(within(form).getByLabelText('Machine')).toHaveValue('1'); // the only machine is preselected
    fireEvent.change(within(form).getByLabelText('Stopped at'), { target: { value: '2026-10-14T08:00' } });
    fireEvent.change(within(form).getByLabelText('Reason'), { target: { value: '  Coolant pump tripped ' } });
    await user.click(within(form).getByRole('button', { name: 'Record downtime' }));
    expect(await within(form).findByRole('status')).toHaveTextContent('Downtime recorded (still down)');
    const [body] = posts(fetchMock, '/downtime-events');
    expect(body).toEqual({
      machine_id: 1,
      started_at: localInputToISO('2026-10-14T08:00'),
      reason: 'Coolant pump tripped',
    });
  });

  it('shows the server’s refusal for a machine that is not assigned', async () => {
    const user = userEvent.setup();
    stubFetch(
      routes({
        '/downtime-events': (url, init) =>
          init?.method === 'POST'
            ? jsonResponse(
                { error: { code: 'machine_not_assigned', message: 'Machine 1 is not assigned to you.', request_id: 'r1' } },
                { status: 403 },
              )
            : jsonResponse(page([])),
      }),
    );
    render(<App />);
    const form = await screen.findByRole('form', { name: 'Report downtime' });
    fireEvent.change(within(form).getByLabelText('Reason'), { target: { value: 'Jam' } });
    await user.click(within(form).getByRole('button', { name: 'Record downtime' }));
    expect(await within(form).findByRole('alert')).toHaveTextContent('This machine is not assigned to you');
  });

  it('tells an operator without machines to ask the administrator', async () => {
    stubFetch(routes({ '/auth/me': jsonResponse(currentUser('operator', { machines: [] })) }));
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'No machines assigned yet' })).toBeInTheDocument();
    expect(screen.queryByRole('form', { name: 'Report downtime' })).not.toBeInTheDocument();
  });
});