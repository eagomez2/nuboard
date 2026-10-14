import { describe, expect, it } from 'vitest';
import { ema, robustRange } from '../src/lib/smooth';
import { sideBySide } from '../src/lib/diff';

describe('ema', () => {
  it('is debiased: a constant series stays constant', () => {
    const out = ema([5, 5, 5, 5], 0.9);
    for (const v of out) expect(v).toBeCloseTo(5);
  });
  it('passes NaN through without poisoning later values', () => {
    const out = ema([1, NaN, 1], 0.5);
    expect(Number.isNaN(out[1])).toBe(true);
    expect(out[2]).toBeCloseTo(1);
  });
  it('weight 0 is the identity', () => {
    expect(Array.from(ema([1, 2, 3], 0))).toEqual([1, 2, 3]);
  });
});

describe('robustRange', () => {
  it('ignores a single huge spike', () => {
    const values = Array.from({ length: 1000 }, (_, i) => 2 + Math.sin(i / 50) * 0.1);
    values[500] = 1e6;
    const [lo, hi] = robustRange([values])!;
    expect(hi).toBeLessThan(10);
    expect(lo).toBeGreaterThan(1.5);
  });
});

describe('sideBySide', () => {
  it('pairs a changed line as a modification', () => {
    const rows = sideBySide('a\nlr: 1\nc\n', 'a\nlr: 2\nc\n');
    expect(rows.map((r) => r.kind)).toEqual(['same', 'mod', 'same']);
  });
});
