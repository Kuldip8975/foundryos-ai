/**
 * Build a query string from a params object.
 *
 * - null, undefined and '' are omitted (an unset filter is not sent at all);
 * - numbers and booleans are stringified;
 * - keys keep their insertion order so URLs are stable and testable.
 *
 * @param {Record<string, unknown>} params
 * @returns {string} '' or '?a=1&b=2'
 */
export function buildQuery(params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue;
    search.append(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}