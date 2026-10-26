import { ApiError, getJson, requestJson } from './client.js';

/** GET /health/live — throws ApiError if the API process is not reachable. */
export function fetchLiveness(options) {
  return getJson('/health/live', options);
}

/**
 * GET /health/ready — 200 (ready) and 503 (not ready) both carry a
 * ReadinessResponse body: { status, checks: [{ name, status, latency_ms, detail }] }.
 */
export async function fetchReadiness(options) {
  const result = await requestJson('/health/ready', options);
  if ((result.status === 200 || result.status === 503) && Array.isArray(result.data?.checks)) {
    return result.data;
  }
  throw new ApiError(result.data?.error?.message ?? `Unexpected readiness response (HTTP ${result.status}).`, {
    kind: 'http',
    status: result.status,
    requestId: result.requestId,
  });
}
