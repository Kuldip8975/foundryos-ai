import { describe, expect, it } from 'vitest';
import { labelIndices, niceStep, niceTicks } from './scale.js';

describe('chart scales', () => {
  it('rounds steps to 1, 2, 2.5 or 5 × 10^n', () => {
    expect(niceStep(0.7)).toBe(1);
    expect(niceStep(180)).toBe(200);
    expect(niceStep(23)).toBe(25);
    expect(niceStep(0.018)).toBe(0.02);
  });

  it('builds ticks from zero that cover the maximum', () => {
    expect(niceTicks(437)).toEqual([0, 100, 200, 300, 400, 500]);
    expect(niceTicks(0.075)).toEqual([0, 0.02, 0.04, 0.06, 0.08]);
    expect(niceTicks(0)).toEqual([0, 1]);
  });

  it('chooses evenly spaced labels including both ends', () => {
    expect(labelIndices(3)).toEqual([0, 1, 2]);
    expect(labelIndices(28, 4)).toEqual([0, 9, 18, 27]);
    expect(labelIndices(0)).toEqual([]);
  });
});