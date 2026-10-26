import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getJson, requestJson } from './client.js';
import { jsonResponse, stubFetch } from '../test/fetchMock.js';
import { SESSION_KEY, onSessionEnded } from '../auth/session.js';

describe('api client', () => {
  it('returns the parsed body on success', async () => {
    stubFetch({ '/thing': jsonResponse({ value: 1 }) });
    await expect(getJson('/thing')).resolves.toEqual({ value: 1 });
  });

  it('maps the backend error envelope to ApiError', async () => {
    stubFetch({
      '/missing': jsonResponse(
        { error: { code: 'not_found', message: 'Not Found', request_id: 'abc' } },
        { status: 404 },
      ),
    });
    const err = await getJson('/missing').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ kind: 'http', status: 404, code: 'not_found', requestId: 'abc' });
  });

  it('reports network failures as kind=network', async () => {
    stubFetch({ '/down': new TypeError('Failed to fetch') });
    await expect(requestJson('/down')).rejects.toMatchObject({ kind: 'network' });
  });

  it('reports timeouts as kind=timeout', async () => {
    stubFetch({
      '/slow': () => new Promise(() => {}), // never resolves on its own
    });
    // fetch mock ignores the abort signal, so emulate fetch's abort behaviour:
    const original = globalThis.fetch;
    globalThis.fetch = (url, init) =>
      new Promise((resolve, reject) => {
        init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        original(url, init).then(resolve, reject);
      });
    await expect(requestJson('/slow', { timeoutMs: 20 })).rejects.toMatchObject({ kind: 'timeout' });
  });

  it('reports non-JSON responses as kind=parse', async () => {
    stubFetch({
      '/html': {
        ok: false,
        status: 502,
        headers: new Headers(),
        json: async () => {
          throw new SyntaxError('Unexpected token <');
        },
      },
    });
    await expect(requestJson('/html')).rejects.toMatchObject({ kind: 'parse', status: 502 });
  });

  it('refuses to send requests without a configured base URL', async () => {
    await expect(requestJson('/x', { baseUrl: '' })).rejects.toMatchObject({ kind: 'config' });
  });
});

describe('api client and the sign-in session', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it('sends no Authorization header when nobody is signed in', async () => {
    const fetchMock = stubFetch({ '/thing': jsonResponse({}) });
    await getJson('/thing');
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });

  it('sends the session token as a bearer header', async () => {
    window.sessionStorage.setItem(SESSION_KEY, 'session-token-0123456789abcdef0123');
    const fetchMock = stubFetch({ '/thing': jsonResponse({}) });
    await getJson('/thing');
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer session-token-0123456789abcdef0123');
  });

  it('ends the session when the server rejects its token', async () => {
    window.sessionStorage.setItem(SESSION_KEY, 'session-token-0123456789abcdef0123');
    const listener = vi.fn();
    const unsubscribe = onSessionEnded(listener);
    stubFetch({
      '/thing': jsonResponse(
        { error: { code: 'session_expired', message: 'Your session has expired. Sign in again.' } },
        { status: 401 },
      ),
    });
    await expect(getJson('/thing')).rejects.toMatchObject({ status: 401, code: 'session_expired' });
    expect(window.sessionStorage.getItem(SESSION_KEY)).toBeNull();
    expect(listener).toHaveBeenCalledWith(expect.objectContaining({ code: 'session_expired' }));
    unsubscribe();
  });

  it('does not end the session for a 403 (signed in, but not allowed)', async () => {
    window.sessionStorage.setItem(SESSION_KEY, 'session-token-0123456789abcdef0123');
    stubFetch({ '/thing': jsonResponse({ error: { code: 'forbidden', message: 'No.' } }, { status: 403 }) });
    await expect(getJson('/thing')).rejects.toMatchObject({ status: 403 });
    expect(window.sessionStorage.getItem(SESSION_KEY)).toBe('session-token-0123456789abcdef0123');
  });
});