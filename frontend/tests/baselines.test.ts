import { describe, expect, it } from 'vitest';
import { baselineExtent, baselineLines } from '../src/lib/baselines';

describe('baselines', () => {
  const series = [
    { label: 'a', baseline: { value: 2.31 } },
    { label: 'b', baseline: { value: 2.3100000001 } },
    { label: 'c', baseline: { value: 2.58, low: 2.5, high: 2.66 } },
    { label: 'd', baseline: null },
    { label: 'e', baseline: { value: 2.31, low: 2.2, high: 2.4 } },
  ];

  it('share a line when equal to 6 significant digits, ranges included', () => {
    const lines = baselineLines(series);
    expect(lines.map((l) => l.labels)).toEqual([['a', 'b'], ['c'], ['e']]);
    expect(lines[0].series).toEqual([0, 1]);
  });

  it('leave out hidden series', () => {
    expect(baselineLines(series, new Set(['a', 'c', 'e'])).map((l) => l.labels)).toEqual([['b']]);
  });

  it('span their ranges', () => {
    expect(baselineExtent(baselineLines(series))).toEqual([2.2, 2.66]);
    expect(baselineExtent([])).toBeNull();
    expect(baselineExtent([{ value: -1 }, { value: 3 }], true)).toEqual([3, 3]);
  });
});
