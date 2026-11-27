import { describe, expect, it } from 'vitest';
import { applySuggestion, complete, quoteValue, type QueryField } from '../src/lib/querycomplete';

const fields: QueryField[] = [
  { name: 'status', kind: 'run', runs: 3, values: ['finished', 'crashed', 'running'] },
  { name: 'tags', kind: 'run', runs: 2, values: ['sweep', 'seeds'] },
  { name: 'project', kind: 'run', runs: 3, values: ['vit-ablations', 'my project'] },
  { name: 'config.optim.lr', kind: 'config', runs: 3, values: [0.001, 0.0003] },
  { name: 'config.augment', kind: 'config', runs: 2, values: ['flip', 'none'] },
  { name: 'fields.stage', kind: 'field', runs: 1, values: ['b'] },
  { name: 'train/loss', kind: 'metric', runs: 2, values: [] },
];

const labels = (text: string, caret = text.length) => complete(text, caret, fields)?.items.map((s) => s.label) ?? [];

describe('complete', () => {
  it('offers examples and fields in an empty bar', () => {
    const c = complete('', 0, fields, ['where status != crashed']);
    expect(c?.items[0]).toMatchObject({ kind: 'example', label: 'where status != crashed' });
    expect(c?.items.map((s) => s.label)).toContain('config.optim.lr');
  });
  it('narrows field names as they are typed, starting matches first', () => {
    expect(labels('where sta')).toEqual(['status', 'fields.stage']);
    expect(labels('where lr')[0]).toBe('config.optim.lr'); // the last part of a config key
    expect(labels('where config.')).toContain('config.augment');
    expect(labels('loss')).toEqual(['train/loss']);
  });
  it('offers operators after a field and values after an operator', () => {
    expect(labels('where status ')).toContain('!=');
    expect(labels('where tags ')).toContain('has');
    expect(labels('where status != ')).toEqual(['finished', 'crashed', 'running']);
    expect(labels('where status = cr')).toEqual(['crashed']);
    expect(labels('where tags has ')).toEqual(['sweep', 'seeds']);
    expect(labels('where optim.lr = ')).toEqual(['0.001', '0.0003']); // a bare config key
    expect(labels('where config.augment in (flip, ')).toEqual(['flip', 'none']);
  });
  it('quotes values that are not one word', () => {
    const c = complete('where project = "my', 19, fields)!;
    expect(c.word).toBe('my');
    expect(c.items.map((s) => s.insert)).toEqual(['"my project"']);
    expect(applySuggestion('where project = "my', c, c.items[0]).text).toBe('where project = "my project" ');
    expect(quoteValue('crashed')).toBe('crashed');
    expect(quoteValue('and')).toBe('"and"');
    expect(quoteValue(0.5)).toBe('0.5');
  });
  it('offers keywords after a full term, and agg names after agg', () => {
    expect(labels('where status = crashed ')).toEqual(['and', 'or', 'group by', 'agg', 'order by', 'limit']);
    expect(labels('where status = crashed group by config.augment ')).toEqual(['agg', 'order by', 'limit']);
    expect(labels('group by config.augment agg ')).toContain('mean±std');
    expect(labels('order by train/loss.min ')).toEqual(['desc', 'asc', 'group by', 'agg', 'limit']);
    expect(labels('order by ')).toContain('train/loss.min');
  });
  it('offers a metric’s statistics after its name and a dot', () => {
    expect(labels('train/loss.')).toEqual([
      'train/loss.last',
      'train/loss.min',
      'train/loss.max',
      'train/loss.count',
      'train/loss.step',
      'train/loss.nonfinite',
    ]);
    expect(labels('train/loss.m')).toEqual(['train/loss.min', 'train/loss.max']);
  });
  it('stays quiet while a number or a limit is typed', () => {
    expect(complete('where config.optim.lr < 1', 25, fields)).toBeNull();
    expect(complete('limit ', 6, fields)).toBeNull();
    expect(complete('where status = crashed and', 26, fields)).toBeNull(); // `and` typed in full
  });
  it('replaces the whole word at the caret, also the part after it', () => {
    const text = 'where stat = crashed';
    const c = complete(text, 9, fields)!;
    expect([c.from, c.to]).toEqual([6, 10]);
    const out = applySuggestion(text, c, c.items[0]);
    expect(out.text).toBe('where status = crashed');
    expect(out.caret).toBe(13);
  });
  it('puts the caret inside an in list', () => {
    const c = complete('where config.augment ', 21, fields)!;
    const inList = c.items.find((s) => s.label === 'in (')!;
    expect(applySuggestion('where config.augment ', c, inList)).toEqual({
      text: 'where config.augment in (',
      caret: 25,
    });
  });
});
