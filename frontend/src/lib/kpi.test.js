import { describe, expect, it } from 'vitest';
import { computeKpis, isSummaryEmpty, safeRatio, trendRows } from './kpi.js';
import { SUMMARY, emptySummary } from '../test/dashboardFixtures.js';

describe('safeRatio', () => {
  it('divides when the denominator is positive', () => {
    expect(safeRatio(45, 50)).toBe(0.9);
  });

  it('returns null instead of 0 or Infinity when there is no denominator', () => {
    expect(safeRatio(5, 0)).toBeNull();
    expect(safeRatio(0, 0)).toBeNull();
    expect(safeRatio(5, null)).toBeNull();
    expect(safeRatio(undefined, 5)).toBeNull();
    expect(safeRatio(5, Number.NaN)).toBeNull();
  });
});

describe('computeKpis', () => {
  const kpis = computeKpis(SUMMARY);

  it('passes totals through unchanged', () => {
    expect(kpis).toMatchObject({
      output: 1800,
      target: 2000,
      accepted: 1700,
      rejected: 60,
      pending: 40,
      recordCount: 6,
      inspected: 400,
      defects: 18,
      downtimeSeconds: 12600,
      downtimeEvents: 3,
      ongoingDowntime: 1,
      openMaintenance: 3,
      criticalOpen: 1,
      highOpen: 1,
      raisedInPeriod: 6,
    });
  });

  it('derives ratios from the totals', () => {
    expect(kpis.targetAchievement).toBeCloseTo(0.9);
    expect(kpis.firstPassYield).toBeCloseTo(1700 / 1760);
    expect(kpis.rejectionRate).toBeCloseTo(60 / 1800);
    expect(kpis.defectRate).toBeCloseTo(18 / 400);
  });

  it('weights the defect rate by volume instead of averaging daily rates', () => {
    const summary = {
      ...SUMMARY,
      quality: { inspection_count: 2, inspected_quantity: 1010, defect_quantity: 11 },
    };
    // 10/1000 on one day and 1/10 on another: pooled = 11/1010, not (1% + 10%) / 2
    expect(computeKpis(summary).defectRate).toBeCloseTo(11 / 1010);
  });

  it('reports unavailable ratios as null when nothing was produced or inspected', () => {
    const empty = computeKpis(emptySummary());
    expect(empty.targetAchievement).toBeNull();
    expect(empty.firstPassYield).toBeNull();
    expect(empty.rejectionRate).toBeNull();
    expect(empty.defectRate).toBeNull();
    expect(empty.output).toBe(0);
  });
});

describe('trendRows', () => {
  it('maps API points and derives per-bucket ratios', () => {
    const rows = trendRows(SUMMARY.trend.points);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toMatchObject({ date: '2026-01-05', actual: 650, target: 700, inspected: 150, defects: 6 });
    expect(rows[1].defectRate).toBeCloseTo(9 / 120);
    expect(rows[2].targetAchievement).toBeCloseTo(590 / 650);
  });

  it('leaves the defect rate empty for buckets without inspections', () => {
    const [row] = trendRows([{ ...SUMMARY.trend.points[0], inspected_quantity: 0, defect_quantity: 0 }]);
    expect(row.defectRate).toBeNull();
  });
});

describe('isSummaryEmpty', () => {
  it('is true only when every section is empty', () => {
    expect(isSummaryEmpty(emptySummary())).toBe(true);
    expect(isSummaryEmpty(SUMMARY)).toBe(false);
    const onlyMaintenance = emptySummary({
      maintenance: { ...emptySummary().maintenance, by_status: { ...emptySummary().maintenance.by_status, open: 1 } },
    });
    expect(isSummaryEmpty(onlyMaintenance)).toBe(false);
  });
});