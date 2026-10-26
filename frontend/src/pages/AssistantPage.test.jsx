import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AssistantPage } from './AssistantPage.jsx';
import { SESSION_KEY } from '../auth/session.js';
import { jsonResponse, stubFetch } from '../test/fetchMock.js';
import { page } from '../test/dashboardFixtures.js';
import {
  HASH,
  OPERATOR,
  SUPERVISOR,
  TOKENS,
  executed,
  proposal,
  session,
  summaryOf,
  withProposal,
} from '../test/workflowFixtures.js';

const ACTORS = { [TOKENS.olga]: OPERATOR, [TOKENS.alice]: SUPERVISOR };

function bearer(init) {
  return init?.headers?.Authorization?.replace(/^Bearer /, '');
}

function apiError(code, message, status, details) {
  return jsonResponse({ error: { code, message, details, request_id: 'req-9' } }, { status });
}

function routes(overrides = {}) {
  return {
    '/workflows/me': (url, init) =>
      ACTORS[bearer(init)]
        ? jsonResponse(ACTORS[bearer(init)])
        : apiError('forbidden', 'Your role does not allow this.', 403),
    '/workflows': (url, init) =>
      init?.method === 'POST'
        ? jsonResponse(session(), { status: 201 })
        : jsonResponse(page([summaryOf(session())])),
    '/workflows/3': jsonResponse(session()),
    ...overrides,
  };
}

function posts(fetchMock, path) {
  return fetchMock.mock.calls
    .filter(([url, init]) => init?.method === 'POST' && new URL(url).pathname.endsWith(path))
    .map(([, init]) => ({ body: JSON.parse(init.body), token: bearer(init) }));
}

// Whole-value input instead of per-key typing: long per-key typing into
// controlled inputs proved flaky (characters out of order) on slower machines.
function fill(input, value) {
  fireEvent.change(input, { target: { value } });
}

/** Since Module 5 the assistant uses the signed-in session; the app shell handles sign-in. */
async function renderAs(name = 'olga') {
  window.sessionStorage.setItem(SESSION_KEY, TOKENS[name]);
  render(<AssistantPage />);
  await screen.findByText(/Using the assistant as/);
}

async function ask(user, question = 'Which machines are down?') {
  fill(screen.getByLabelText('Your question'), question);
  await user.click(screen.getByRole('button', { name: 'Ask' }));
}

// These page tests render the whole assistant; allow for slower machines.
vi.setConfig({ testTimeout: 20_000 });

beforeEach(() => {
  window.sessionStorage.clear();
});

describe('AssistantPage — session', () => {
  it('uses the signed-in session and shows the assistant role', async () => {
    const fetchMock = stubFetch(routes());
    await renderAs('olga');
    expect(screen.getByRole('heading', { level: 2, name: 'Workflow assistant' })).toBeInTheDocument();
    expect(screen.getByText(/Using the assistant as/)).toHaveTextContent('Using the assistant as olga (Operator)');
    const me = fetchMock.mock.calls.find(([url]) => new URL(url).pathname.endsWith('/workflows/me'));
    expect(bearer(me[1])).toBe(TOKENS.olga);
    expect(screen.queryByLabelText('Access token')).not.toBeInTheDocument();
  });

  it('explains when the role has no assistant access', async () => {
    window.sessionStorage.setItem(SESSION_KEY, 'an-admin-session-token-0123456789abcdef');
    stubFetch(routes());
    render(<AssistantPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Your role does not allow this');
    expect(screen.queryByLabelText('Your question')).not.toBeInTheDocument();
  });
});

describe('AssistantPage — questions', () => {
  it('validates the question before sending it', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(routes());
    await renderAs();
    await user.click(screen.getByRole('button', { name: 'Ask' }));
    expect(screen.getByText(/at least 3 characters/)).toBeInTheDocument();
    expect(posts(fetchMock, '/workflows')).toEqual([]);
  });

  it('shows progress, then the evidence-backed answer, tool calls and audit trail', async () => {
    const user = userEvent.setup();
    let resolve;
    const fetchMock = stubFetch(
      routes({
        '/workflows': (url, init) =>
          init?.method === 'POST'
            ? new Promise((r) => {
                resolve = () => r(jsonResponse(session(), { status: 201 }));
              })
            : jsonResponse(page([])),
      }),
    );
    await renderAs();
    await ask(user);

    expect(await screen.findByText(/querying plant data with allowlisted tools/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Working…' })).toBeDisabled();
    resolve();

    const answer = await screen.findByRole('article', { name: 'Answer 3' });
    expect(within(answer).getByText(/AI-generated answer/)).toBeInTheDocument();
    expect(within(answer).getByText('MILL is down; LATHE is running.')).toBeInTheDocument();
    expect(within(answer).getByRole('list', { name: 'Evidence' })).toHaveTextContent('E1 Machine status');
    expect(within(answer).getByText(/not live telemetry/)).toBeInTheDocument();

    const steps = screen.getByRole('list', { name: 'Tool calls' });
    expect(steps).toHaveTextContent('Machine status');
    expect(within(steps).getByText('Ran')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Audit trail' })).toHaveTextContent('Workflow completed');

    expect(posts(fetchMock, '/workflows')).toEqual([{ body: { question: 'Which machines are down?' }, token: TOKENS.olga }]);
  });

  it('labels refused tool calls', async () => {
    const user = userEvent.setup();
    const refused = session({
      steps: [
        {
          ...session().steps[0],
          id: 99,
          tool: 'run_sql',
          status: 'rejected',
          evidence_id: null,
          result: null,
          error_code: 'unknown_tool',
          error_message: "'run_sql' is not an available tool.",
        },
      ],
      answer: { answer: 'I could not run that.', findings: [], limitations: [] },
    });
    stubFetch(routes({ '/workflows': (url, init) => (init?.method === 'POST' ? jsonResponse(refused, { status: 201 }) : jsonResponse(page([]))) }));
    await renderAs();
    await ask(user);
    const steps = await screen.findByRole('list', { name: 'Tool calls' });
    expect(steps).toHaveTextContent('Unknown tool “run_sql”');
    expect(within(steps).getByText('Refused')).toBeInTheDocument();
    expect(steps).toHaveTextContent('is not an available tool');
  });

  it('shows provider errors with a link to the saved failed attempt', async () => {
    const user = userEvent.setup();
    stubFetch(
      routes({
        '/workflows': (url, init) =>
          init?.method === 'POST'
            ? apiError('ai_rate_limited', "The AI provider's rate limit was reached. Try again later.", 429, [{ session_id: 3 }])
            : jsonResponse(page([])),
        '/workflows/3': jsonResponse(
          session({
            status: 'failed',
            answer: null,
            steps: [],
            error_code: 'ai_rate_limited',
            error_message: "The AI provider's rate limit was reached. Try again later.",
          }),
        ),
      }),
    );
    await renderAs();
    await ask(user);
    expect(await screen.findByRole('alert')).toHaveTextContent('The AI provider is rate-limiting requests');
    await user.click(screen.getByRole('button', { name: 'View the saved failed attempt (#3)' }));
    expect(await screen.findByText(/No answer\./)).toBeInTheDocument();
    expect(screen.getByText('The assistant answered without calling any tools.')).toBeInTheDocument();
  });

  it('reports an unreachable API', async () => {
    const user = userEvent.setup();
    stubFetch(
      routes({
        '/workflows': (url, init) => {
          if (init?.method === 'POST') throw new TypeError('Failed to fetch');
          return jsonResponse(page([]));
        },
      }),
    );
    await renderAs();
    await ask(user);
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach the FoundryOS API');
  });

  it('opens a past workflow from the history', async () => {
    const user = userEvent.setup();
    stubFetch(routes());
    await renderAs();
    const history = await screen.findByRole('table', { name: 'Workflow sessions' });
    expect(history).toHaveTextContent('Which machines are down?');
    await user.click(within(history).getByRole('button', { name: 'View workflow 3' }));
    expect(await screen.findByRole('article', { name: 'Answer 3' })).toBeInTheDocument();
  });
});

describe('AssistantPage — approvals', () => {
  it('lets the operator who prepared an action wait or withdraw, but not approve', async () => {
    const user = userEvent.setup();
    const withdrawn = proposal({
      status: 'rejected',
      approval: { decision: 'rejected', actor: 'olga', actor_role: 'operator', arguments_hash: HASH, note: null, created_at: '2026-10-15T08:03:00Z' },
    });
    const fetchMock = stubFetch(
      routes({
        '/workflows': (url, init) =>
          init?.method === 'POST' ? jsonResponse(withProposal(), { status: 201 }) : jsonResponse(page([])),
        '/workflows/proposals/7/reject': jsonResponse(withdrawn),
        '/workflows/3': jsonResponse(withProposal(session(), withdrawn)),
      }),
    );
    await renderAs('olga');
    await ask(user, 'Prepare a maintenance request for MILL vibration');

    const panel = await screen.findByRole('region', { name: 'Proposed action' });
    expect(within(panel).getByText('Awaiting approval')).toBeInTheDocument();
    expect(panel).toHaveTextContent('MILL — Mill');
    expect(panel).toHaveTextContent('Spindle vibration above normal');
    expect(panel).toHaveTextContent('ab12cd34ef56');
    expect(within(panel).queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument();
    expect(panel).toHaveTextContent('Waiting for a supervisor');

    await user.click(within(panel).getByRole('button', { name: 'Withdraw proposal' }));
    await waitFor(() => expect(screen.getByRole('region', { name: 'Proposed action' })).toHaveTextContent('Withdrawn by olga'));
    const [reject] = posts(fetchMock, '/proposals/7/reject');
    expect(reject.token).toBe(TOKENS.olga);
    expect(reject.body.idempotency_key).toMatch(/^ui-/);
  });

  it('approves exactly the displayed action and shows the confirmed result', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(
      routes({
        '/workflows': (url, init) =>
          init?.method === 'POST' ? jsonResponse(withProposal(), { status: 201 }) : jsonResponse(page([])),
        '/workflows/proposals/7/approve': jsonResponse(executed()),
        '/workflows/3': jsonResponse(withProposal(session(), executed())),
      }),
    );
    await renderAs('alice');
    await ask(user);

    const panel = await screen.findByRole('region', { name: 'Proposed action' });
    const approveButton = within(panel).getByRole('button', { name: 'Approve and create request' });
    expect(approveButton).toBeDisabled(); // a deliberate review step comes first
    await user.click(within(panel).getByLabelText(/I have reviewed this action/));
    fill(within(panel).getByLabelText('Note (optional)'), 'Checked on the floor.');
    await user.click(approveButton);

    await waitFor(() =>
      expect(screen.getByRole('region', { name: 'Proposed action' })).toHaveTextContent(
        'Maintenance request #42 was created and confirmed in the database',
      ),
    );
    expect(within(screen.getByRole('region', { name: 'Proposed action' })).getByText('Executed')).toBeInTheDocument();
    const [approval] = posts(fetchMock, '/proposals/7/approve');
    expect(approval.token).toBe(TOKENS.alice);
    expect(approval.body).toEqual({
      arguments_hash: HASH,
      idempotency_key: expect.stringMatching(/^ui-/),
      note: 'Checked on the floor.',
    });
  });

  it('reuses the idempotency key when an approval is retried after a network error', async () => {
    const user = userEvent.setup();
    let attempts = 0;
    const fetchMock = stubFetch(
      routes({
        '/workflows': (url, init) =>
          init?.method === 'POST' ? jsonResponse(withProposal(), { status: 201 }) : jsonResponse(page([])),
        '/workflows/proposals/7/approve': () => {
          attempts += 1;
          if (attempts === 1) throw new TypeError('Failed to fetch');
          return jsonResponse(executed());
        },
        '/workflows/3': jsonResponse(withProposal(session(), executed())),
      }),
    );
    await renderAs('alice');
    await ask(user);
    const panel = await screen.findByRole('region', { name: 'Proposed action' });
    await user.click(within(panel).getByLabelText(/I have reviewed this action/));
    await user.click(within(panel).getByRole('button', { name: 'Approve and create request' }));
    expect(await within(panel).findByRole('alert')).toHaveTextContent('Cannot reach the FoundryOS API');

    await user.click(within(panel).getByRole('button', { name: 'Approve and create request' }));
    await waitFor(() =>
      expect(screen.getByRole('region', { name: 'Proposed action' })).toHaveTextContent('Maintenance request #42'),
    );
    const [first, second] = posts(fetchMock, '/proposals/7/approve');
    expect(second.body.idempotency_key).toBe(first.body.idempotency_key);
  });

  it('explains an expired proposal and refreshes its status', async () => {
    const user = userEvent.setup();
    stubFetch(
      routes({
        '/workflows': (url, init) =>
          init?.method === 'POST' ? jsonResponse(withProposal(), { status: 201 }) : jsonResponse(page([])),
        '/workflows/proposals/7/approve': apiError(
          'proposal_expired',
          'This proposal has expired. Ask the assistant again to prepare a new one.',
          409,
        ),
        '/workflows/3': jsonResponse(withProposal(session(), proposal({ status: 'expired' }))),
      }),
    );
    await renderAs('alice');
    await ask(user);
    const panel = await screen.findByRole('region', { name: 'Proposed action' });
    await user.click(within(panel).getByLabelText(/I have reviewed this action/));
    await user.click(within(panel).getByRole('button', { name: 'Approve and create request' }));

    await waitFor(() =>
      expect(screen.getByRole('region', { name: 'Proposed action' })).toHaveTextContent(
        'This proposal expired before anyone approved it',
      ),
    );
    expect(screen.queryByRole('button', { name: 'Approve and create request' })).not.toBeInTheDocument();
  });
});