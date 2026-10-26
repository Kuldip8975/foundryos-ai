import { describe, expect, it } from 'vitest';
import {
  approveProposal,
  fetchMe,
  newIdempotencyKey,
  rejectProposal,
  runWorkflow,
  validateQuestion,
} from './workflows.js';
import { jsonResponse, stubFetch } from '../test/fetchMock.js';

const TOKEN = 'a-test-token-that-is-long-enough';

function lastCall(fetchMock) {
  const [url, init] = fetchMock.mock.calls.at(-1);
  return { url: new URL(url), init, body: init.body ? JSON.parse(init.body) : undefined };
}

describe('workflow api', () => {
  it('validates questions like the server does', () => {
    expect(validateQuestion('')).toMatch(/at least 3/);
    expect(validateQuestion('  hi ')).toMatch(/at least 3/);
    expect(validateQuestion('Why?')).toBeNull();
    expect(validateQuestion('x'.repeat(1001))).toMatch(/under 1000/);
  });

  it('creates distinct idempotency keys the server accepts', () => {
    const keys = new Set(Array.from({ length: 20 }, newIdempotencyKey));
    expect(keys.size).toBe(20);
    for (const key of keys) expect(key).toMatch(/^[A-Za-z0-9_-]{16,64}$/);
  });

  it('sends the access token as a bearer header', async () => {
    const fetchMock = stubFetch({ '/workflows/me': jsonResponse({ name: 'olga' }) });
    await fetchMe(TOKEN);
    expect(lastCall(fetchMock).init.headers.Authorization).toBe(`Bearer ${TOKEN}`);
  });

  it('posts the trimmed question', async () => {
    const fetchMock = stubFetch({ '/workflows': jsonResponse({ id: 1 }, { status: 201 }) });
    await expect(runWorkflow(TOKEN, '  Which machines are down?  ')).resolves.toEqual({ id: 1 });
    expect(lastCall(fetchMock).body).toEqual({ question: 'Which machines are down?' });
  });

  it('binds an approval to the proposal hash and omits an empty note', async () => {
    const fetchMock = stubFetch({
      '/workflows/proposals/7/approve': jsonResponse({ id: 7, status: 'executed' }),
      '/workflows/proposals/7/reject': jsonResponse({ id: 7, status: 'rejected' }),
    });
    await approveProposal(TOKEN, 7, { argumentsHash: 'f'.repeat(64), idempotencyKey: 'ui-key-0000000000000', note: '  ' });
    expect(lastCall(fetchMock).body).toEqual({ arguments_hash: 'f'.repeat(64), idempotency_key: 'ui-key-0000000000000' });

    await rejectProposal(TOKEN, 7, { idempotencyKey: 'ui-key-1111111111111', note: 'Duplicate' });
    const call = lastCall(fetchMock);
    expect(call.url.pathname).toBe('/api/v1/workflows/proposals/7/reject');
    expect(call.body).toEqual({ idempotency_key: 'ui-key-1111111111111', note: 'Duplicate' });
    expect(call.init.headers.Authorization).toBe(`Bearer ${TOKEN}`);
  });

  it('surfaces server errors with their code', async () => {
    stubFetch({
      '/workflows/proposals/7/approve': jsonResponse(
        { error: { code: 'approval_mismatch', message: 'Does not match', request_id: 'r' } },
        { status: 409 },
      ),
    });
    await expect(
      approveProposal(TOKEN, 7, { argumentsHash: '0'.repeat(64), idempotencyKey: 'ui-key-2222222222222' }),
    ).rejects.toMatchObject({ kind: 'http', status: 409, code: 'approval_mismatch' });
  });
});