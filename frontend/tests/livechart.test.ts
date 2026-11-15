import { describe, expect, it } from 'vitest';
import type { ChartData, Series } from '../src/lib/api';
import { mergeSeries, runsToRefetch } from '../src/lib/livechart';

const series = (key: string, label: string, y: number[]): Series => ({
  label,
  runs: [key],
  group: null,
  last: y[y.length - 1] ?? null,
  nonfinite: false,
  x: Float64Array.from(y.map((_, i) => i)),
  y: Float64Array.from(y),
  lo: Float64Array.from(y),
  hi: Float64Array.from(y),
});
const chart = (...s: Series[]): ChartData => ({ metric: 'loss', xKind: 'step', series: s });

describe('live chart updates', () => {
  it('refetches only the changed runs of an ungrouped chart', () => {
    expect(runsToRefetch(['a', 'b'], ['b', 'z'], false, true)).toEqual(['b']);
    expect(runsToRefetch(['a', 'b'], ['z'], false, true)).toEqual([]);
    expect(runsToRefetch(['a', 'b'], ['b'], true, true)).toBeNull();
    expect(runsToRefetch(['a', 'b'], null, false, true)).toBeNull();
    expect(runsToRefetch(['a', 'b'], ['b'], false, false)).toBeNull();
  });

  it('merges refetched series in run order and keeps their labels', () => {
    const old = chart(series('a', 'A', [1]), series('b', 'same (b)', [2]), series('c', 'same (c)', [3]));
    const got = mergeSeries(old, chart(series('b', 'same', [2, 4])), ['b'], ['a', 'b', 'c']);
    expect(got?.series.map((s) => s.label)).toEqual(['A', 'same (b)', 'same (c)']);
    expect(Array.from(got!.series[1].y)).toEqual([2, 4]);
  });

  it('adds a run that just started logging, unless its label clashes', () => {
    const old = chart(series('a', 'A', [1]));
    expect(mergeSeries(old, chart(series('b', 'B', [5])), ['b'], ['b', 'a'])?.series.map((s) => s.label)).toEqual([
      'B',
      'A',
    ]);
    expect(mergeSeries(old, chart(series('b', 'A', [5])), ['b'], ['a', 'b'])).toBeNull();
  });
});
