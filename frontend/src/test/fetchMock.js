import { vi } from 'vitest';

/** Build a fetch Response-like object for tests. */
export function jsonResponse(body, { status = 200, requestId = 'req-test' } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'x-request-id': requestId }),
    json: async () => body,
  };
}

/**
 * Stub global fetch with a route table keyed by path (query string ignored):
 *   { '/health/live': response | Error | (url: URL, init) => response | Promise<response> }
 */
export function stubFetch(routes) {
  const fetchMock = vi.fn(async (url, init) => {
    const parsed = new URL(url);
    const path = parsed.pathname.replace(/^\/api\/v1/, '');
    const handler = routes[path];
    if (handler instanceof Error) throw handler;
    if (!handler) throw new TypeError(`Unexpected request in test: ${url}`);
    return typeof handler === 'function' ? handler(parsed, init) : handler;
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** Query parameters of every request the mock received for `path`. */
export function requestsTo(fetchMock, path) {
  return fetchMock.mock.calls
    .map(([url]) => new URL(url))
    .filter((url) => url.pathname.replace(/^\/api\/v1/, '') === path)
    .map((url) => url.searchParams);
}