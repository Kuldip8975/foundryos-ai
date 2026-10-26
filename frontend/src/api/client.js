/**
 * Minimal HTTP client for the FoundryOS API.
 *
 * - Applies the configured base URL, optional query parameters and a request timeout.
 * - Parses the backend's standard error envelope:
 *     { "error": { "code", "message", "details", "request_id" } }
 * - Normalises network, timeout and parse failures into ApiError.
 * - Sends the signed-in person's session token (Module 5) as
 *   `Authorization: Bearer <token>`, and ends the session in the app when the
 *   server answers 401 to a request that carried it (expired or revoked).
 */

import { endSession, getSessionToken } from '../auth/session.js';
import { config } from '../config/env.js';
import { buildQuery } from './query.js';

export class ApiError extends Error {
  /**
   * @param {string} message
   * @param {{kind: 'config'|'network'|'timeout'|'http'|'parse', status?: number, code?: string, requestId?: string|null}} info
   */
  constructor(message, { kind, status = null, code = null, requestId = null, details = null }) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }
}

/**
 * Perform a request and return the parsed JSON regardless of HTTP status.
 * Throws ApiError only when no usable JSON response was received.
 *
 * @returns {Promise<{ok: boolean, status: number, data: any, requestId: string|null}>}
 */
export async function requestJson(
  path,
  { method = 'GET', signal, timeoutMs, baseUrl, params, body, headers } = {},
) {
  const root = baseUrl ?? config.apiBaseUrl;
  if (!root) {
    throw new ApiError(config.configError ?? 'API base URL is not configured.', { kind: 'config' });
  }

  const sessionToken = getSessionToken();
  const authorization = headers?.Authorization ?? (sessionToken ? `Bearer ${sessionToken}` : null);

  const timeoutController = new AbortController();
  const timer = setTimeout(() => timeoutController.abort(), timeoutMs ?? config.requestTimeoutMs);
  const onExternalAbort = () => timeoutController.abort();
  signal?.addEventListener('abort', onExternalAbort, { once: true });

  let response;
  try {
    response = await fetch(`${root}${path}${buildQuery(params)}`, {
      method,
      headers: {
        Accept: 'application/json',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(authorization ? { Authorization: authorization } : {}),
        ...(headers ?? {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: timeoutController.signal,
    });
  } catch (err) {
    if (signal?.aborted) throw err; // caller cancelled: propagate as-is
    if (timeoutController.signal.aborted) {
      throw new ApiError('The server did not respond in time.', { kind: 'timeout' });
    }
    throw new ApiError('Could not reach the FoundryOS API.', { kind: 'network' });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onExternalAbort);
  }

  const requestId = response.headers.get('x-request-id');
  let data;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(`Unexpected non-JSON response (HTTP ${response.status}).`, {
      kind: 'parse',
      status: response.status,
      requestId,
    });
  }
  if (response.status === 401 && sessionToken && authorization === `Bearer ${sessionToken}`) {
    // The server no longer accepts this session: return to the sign-in page.
    endSession(httpError({ status: 401, data, requestId }));
  }
  return { ok: response.ok, status: response.status, data, requestId };
}

function httpError(result) {
  const envelope = result.data?.error;
  return new ApiError(envelope?.message ?? `Request failed (HTTP ${result.status}).`, {
    kind: 'http',
    status: result.status,
    code: envelope?.code ?? null,
    requestId: envelope?.request_id ?? result.requestId,
    details: Array.isArray(envelope?.details) ? envelope.details : null,
  });
}

/** GET that resolves with the body on 2xx and throws ApiError otherwise. */
export async function getJson(path, options) {
  const result = await requestJson(path, options);
  if (result.ok) return result.data;
  throw httpError(result);
}

/**
 * Request with a JSON body (default POST). Resolves with { status, data } on 2xx
 * so callers can tell 200 from 201; throws ApiError otherwise.
 */
export async function sendJson(path, { method = 'POST', body, ...options } = {}) {
  const result = await requestJson(path, { ...options, method, body });
  if (result.ok) return { status: result.status, data: result.data };
  throw httpError(result);
}