/**
 * Evidence lookup for AI reports.
 *
 * The backend flattens the metrics snapshot into keys such as
 * "production.actual_quantity" or "downtime.by_machine.0.downtime_seconds",
 * and the AI must cite those keys. This mirrors that flattening so each cited
 * key can be shown next to its measured value.
 */

import { formatDuration, formatNumber, formatPercent, MISSING } from './format.js';

export function flattenMetrics(metrics, prefix = '') {
  const flat = {};
  for (const [key, value] of Object.entries(metrics ?? {})) {
    const path = `${prefix}${key}`;
    if (Array.isArray(value)) {
      if (value.length === 0) flat[path] = [];
      value.forEach((item, index) => {
        if (item && typeof item === 'object') Object.assign(flat, flattenMetrics(item, `${path}.${index}.`));
        else flat[`${path}.${index}`] = item;
      });
    } else if (value && typeof value === 'object') {
      Object.assign(flat, flattenMetrics(value, `${path}.`));
    } else {
      flat[path] = value;
    }
  }
  return flat;
}

const RATIO_KEYS = /(achievement|_rate|first_pass_yield)(_change)?$/;

/** Display a metric value according to its key. */
export function formatMetricValue(key, value) {
  if (value === null || value === undefined) return 'not available';
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'none';
  if (typeof value === 'number') {
    if (RATIO_KEYS.test(key)) {
      if (!key.endsWith('_change')) return formatPercent(value);
      // A difference between two ratios is in percentage points, not percent.
      const points = (value * 100).toFixed(1);
      return `${value > 0 ? '+' : ''}${points} pp`;
    }
    if (key.endsWith('_seconds_change')) return `${value > 0 ? '+' : value < 0 ? '-' : ''}${formatDuration(Math.abs(value))}`;
    if (key.endsWith('_seconds')) return formatDuration(value);
    const text = formatNumber(value);
    return key.endsWith('_change') && value > 0 ? `+${text}` : text;
  }
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  return String(value) || MISSING;
}