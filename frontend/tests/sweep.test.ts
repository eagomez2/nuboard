import { describe, expect, it } from 'vitest';
import { importance, makeAxis, norm } from '../src/lib/sweep';

describe('sweep axes', () => {
  it('uses a log scale for wide positive ranges', () => {
    const axis = makeAxis('lr', [1e-4, 3e-4, 1e-3, 3e-3]);
    expect(axis.numeric && axis.log).toBe(true);
    expect(norm(axis, 1e-4)).toBe(0);
    expect(norm(axis, 3e-3)).toBeCloseTo(1);
    expect(norm(axis, 1e-3)!).toBeGreaterThan(0.5);
  });

  it('treats mixed values as ordered categories', () => {
    const axis = makeAxis('aug', ['mixup', 'none', null, 'cutmix']);
    expect(axis.numeric).toBe(false);
    expect(axis.categories).toEqual(['—', 'cutmix', 'mixup', 'none']);
    expect(norm(axis, 'none')).toBe(1);
  });
});

describe('importance', () => {
  it('is 1 for a monotonic numeric relation and ignores missing metrics', () => {
    expect(importance([1, 2, 3, 4, 5], [10, 20, 30, null, 50])).toBeCloseTo(1);
  });

  it('measures how well categories separate the metric', () => {
    const strong = importance(['a', 'a', 'b', 'b'], [1, 1.1, 5, 5.2])!;
    const weak = importance(['a', 'b', 'a', 'b'], [1, 1.1, 5, 5.2])!;
    expect(strong).toBeGreaterThan(0.8);
    expect(weak).toBeLessThan(0.5);
  });

  it('needs at least three runs', () => {
    expect(importance([1, 2], [1, 2])).toBeNull();
  });
});
