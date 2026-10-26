/** Small, dependency-free scale helpers for the SVG charts. */

/** Round a raw step up to 1, 2, 2.5 or 5 × 10^n. */
export function niceStep(raw) {
  if (!(raw > 0) || !Number.isFinite(raw)) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const residual = raw / magnitude;
  const nice = residual <= 1 ? 1 : residual <= 2 ? 2 : residual <= 2.5 ? 2.5 : residual <= 5 ? 5 : 10;
  return nice * magnitude;
}

/**
 * Ticks from 0 to a rounded maximum covering `max`.
 * niceTicks(437) → [0, 100, 200, 300, 400, 500]
 */
export function niceTicks(max, count = 5) {
  if (!(max > 0) || !Number.isFinite(max)) return [0, 1];
  const step = niceStep(max / count);
  const top = Math.ceil(max / step) * step;
  const ticks = [];
  for (let value = 0; value <= top + step / 2; value += step) {
    ticks.push(Number(value.toPrecision(12)));
  }
  return ticks;
}

/** Up to `maxLabels` evenly spaced indices, always including first and last. */
export function labelIndices(length, maxLabels = 6) {
  if (length <= 0) return [];
  if (length <= maxLabels) return Array.from({ length }, (_, i) => i);
  const result = new Set([0, length - 1]);
  const step = (length - 1) / (maxLabels - 1);
  for (let i = 1; i < maxLabels - 1; i += 1) result.add(Math.round(i * step));
  return [...result].sort((a, b) => a - b);
}