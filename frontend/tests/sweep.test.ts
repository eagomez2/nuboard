import { describe, expect, it } from 'vitest';
import {
  defaultParams,
  groupByPrefix,
  importance,
  makeAxis,
  norm,
  OTHER,
  paramInfo,
  type ParamInfo,
} from '../src/lib/sweep';

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

describe('the parameter picker', () => {
  it('caps a category axis at its most common values plus other', () => {
    const values = [...Array.from({ length: 20 }, (_, i) => `v${i}`), 'v0', 'v0', 'v1'];
    const axis = makeAxis('id', values, 4);
    expect(axis.categories).toEqual(['v0', 'v1', 'v2', OTHER]); // ties keep first-seen order;
    expect(norm(axis, 'v7')).toBe(1); // gathered in other
    expect(norm(axis, 'v0')).toBe(0);
  });

  it('describes a key: type, distinct values, ids, many values and long text', () => {
    const m = [1, 2, 3, 4];
    expect(paramInfo('lr', [1, 2, 3, 4], m)).toMatchObject({ numeric: true, distinct: 4, unique: false, score: 1 });
    expect(paramInfo('run_id', ['a', 'b', 'c', 'd'], m)).toMatchObject({ numeric: false, unique: true });
    expect(paramInfo('note', ['x'.repeat(41), 'y', 'y', 'y'], m).long).toBe(true);
    const many = paramInfo('k', Array.from({ length: 13 }, (_, i) => `v${i % 13}`).concat(['v0']), [
      ...Array(14).keys(),
    ]);
    expect(many.many).toBe(true);
  });

  it('defaults to the keys most associated with the objective, skipping noise', () => {
    const info = (key: string, score: number | null, extra = {}) =>
      ({ key, numeric: true, distinct: 3, unique: false, many: false, long: false, score, ...extra }) as ParamInfo;
    const infos = [
      info('optim.lr', 0.4),
      info('model.width', 0.9),
      info('seed', 1),
      info('data.path', 1),
      info('out_dir', 1),
      info('run_id', 1, { unique: true }),
      info('labels', 1, { many: true }),
      info('prompt', 1, { long: true }),
      info('fields.owner', 0.4),
      info('optim.wd', null),
      info('logging.every', 0.95),
    ];
    expect(defaultParams(infos, (k) => k.startsWith('logging.'))).toEqual([
      'model.width',
      'optim.lr',
      'fields.owner',
      'optim.wd',
    ]);
    expect(defaultParams(infos, undefined, 1)).toEqual(['logging.every']);
  });

  it('groups keys under their prefix', () => {
    const groups = groupByPrefix([{ key: 'optim.lr' }, { key: 'seed' }, { key: 'optim.wd' }, { key: 'a.b.c' }]);
    expect(groups.map((g) => [g.prefix, g.items.map((i) => i.key)])).toEqual([
      ['optim', ['optim.lr', 'optim.wd']],
      ['', ['seed']],
      ['a.b', ['a.b.c']],
    ]);
  });
});
