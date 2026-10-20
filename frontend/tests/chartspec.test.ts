import { describe, expect, it } from 'vitest';
import { decodeSpec, encodeSpec, type ChartSpec } from '../src/lib/chartspec';

describe('chart specs', () => {
  it('round-trips through the query string', () => {
    const s: ChartSpec = {
      metric: 'val/acc',
      runs: ['vit/runs/a_b', 'vit/runs/c "d"'],
      x: 'step',
      group: 'config.lr',
      agg: 'minmax',
      smooth: 0.6,
      raw: false,
      robust: true,
      log: true,
      base: false,
      zoom: [10, 20.5],
      hidden: ['lr=1e-3', 'a b'],
    };
    const text = encodeSpec(s);
    expect(text).not.toMatch(/["\s)]/); // safe inside a Markdown image title
    expect(decodeSpec(text)).toEqual(s);
  });

  it('draws baselines in specs saved before they existed', () => {
    expect(decodeSpec('metric=loss&runs=a')?.base).toBe(true);
  });

  it('rejects specs without a metric or runs', () => {
    expect(decodeSpec('metric=loss')).toBeNull();
    expect(decodeSpec('runs=a')).toBeNull();
  });
});
