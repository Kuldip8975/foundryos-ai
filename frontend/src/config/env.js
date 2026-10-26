/**
 * Runtime configuration derived from Vite environment variables.
 *
 * VITE_API_BASE_URL must be an absolute http(s) URL ending at the versioned
 * API root, e.g. http://localhost:8000/api/v1. A missing or malformed value
 * is reported in the UI instead of crashing the app.
 */

export function parseApiBaseUrl(raw) {
  if (!raw || !String(raw).trim()) {
    return { apiBaseUrl: null, error: 'VITE_API_BASE_URL is not set. Copy .env.example to .env and set it.' };
  }
  let url;
  try {
    url = new URL(String(raw).trim());
  } catch {
    return { apiBaseUrl: null, error: `VITE_API_BASE_URL is not a valid URL: "${raw}"` };
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return { apiBaseUrl: null, error: 'VITE_API_BASE_URL must use http or https.' };
  }
  return { apiBaseUrl: url.toString().replace(/\/+$/, ''), error: null };
}

const parsed = parseApiBaseUrl(import.meta.env.VITE_API_BASE_URL);

export const config = Object.freeze({
  apiBaseUrl: parsed.apiBaseUrl,
  configError: parsed.error,
  mode: import.meta.env.MODE,
  // Public demo deployments only: the shared password of the demo accounts
  // (created by `python -m app.cli.demo_accounts`). Empty everywhere else.
  demoPassword: import.meta.env.VITE_DEMO_PASSWORD || null,
  requestTimeoutMs: 8000,
});
