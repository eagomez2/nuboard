import { describe, expect, it } from 'vitest';
import { bestIndex, edge2d, niceTicks, padded, parseRowId, rankOf, rowId } from '../src/lib/selection';

describe('select page helpers', () => {
  it('round-trips a row id, even when the run key has an @', () => {
    expect(parseRowId(rowId('vit/a@b', 1500))).toEqual({ key: 'vit/a@b', step: 1500 });
    expect(parseRowId('nostep')).toBeNull();
    expect(parseRowId('run@1.5')).toBeNull();
  });

  it('finds the best row of each column by its direction', () => {
    const rows = [
      [0.8, 0.3],
      [0.9, 0.4],
      [0.7, 0.1],
    ];
    expect(bestIndex(rows, ['max', 'min'])).toEqual([1, 2]);
    expect(bestIndex([], ['max'])).toEqual([-1]);
  });

  it('ranks the best value first and lets ties share a rank', () => {
    expect(rankOf([3, 1, 2, 1], 1, 'min')).toBe(1);
    expect(rankOf([3, 1, 2, 1], 2, 'min')).toBe(3);
    expect(rankOf([3, 1, 2], 3, 'max')).toBe(1);
  });

  it('makes round ticks inside the range', () => {
    expect(niceTicks(0.78, 0.86, 4)).toEqual([0.78, 0.8, 0.82, 0.84, 0.86]);
    expect(niceTicks(0, 10, 5)).toEqual([0, 2, 4, 6, 8, 10]);
    expect(niceTicks(1, 1)).toEqual([1]);
  });

  it('pads a range, and widens a single value', () => {
    const [lo, hi] = padded([1, 2]);
    expect(lo).toBeLessThan(1);
    expect(hi).toBeGreaterThan(2);
    expect(padded([5])[0]).toBeLessThan(5);
    expect(padded([])).toEqual([0, 1]);
  });

  it('draws the trade-off edge through the points not beaten on both axes', () => {
    const pts: [number, number][] = [
      [0.9, 0.05],
      [0.8, 0.02],
      [0.85, 0.04],
      [0.7, 0.03], // beaten by (0.8, 0.02)
      [0.95, 0.06],
    ];
    // higher x and lower y are better
    expect(edge2d(pts, 'max', 'min')).toEqual([
      [0.8, 0.02],
      [0.85, 0.04],
      [0.9, 0.05],
      [0.95, 0.06],
    ]);
  });
});
